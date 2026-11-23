"""
tests/test_mllp.py
Comprehensive unit and integration tests for MLLP (Minimal Lower Layer Protocol)
framing, HL7 ACK generation, and asyncio listener service.
"""

import asyncio
import os
import socket
import pytest
from synapse.mllp import (
    MLLP_START_BLOCK,
    MLLP_END_BLOCK,
    frame_mllp,
    unframe_mllp,
    generate_hl7_ack,
    MLLPListener,
    send_mllp_message_async,
)
from synapse.storage import WalletStorage

SAMPLE_HL7_ORU = (
    "MSH|^~\\&|LAB_SYSTEM|HOSPITAL_A|SYNAPSE_LIMS|LIFECARE|20261121100000||ORU^R01|MSG-99001|P|2.5.1\r"
    "PID|1||SYN-9901^^^MRN||Kapoor^Aakash||19850615|M\r"
    "OBR|1||REP-99001|CBC^Complete Blood Count|||20261121093000\r"
    "OBX|1|NM|718-7^Haemoglobin^LN||14.5|g/dL|13.0-17.0|N|||F\r"
    "OBX|2|NM|6690-2^WBC^LN||7200|cells/mcL|4000-11000|N|||F\r"
)


def get_free_port() -> int:
    """Find an available ephemeral port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_mllp_framing_and_unframing_roundtrip():
    """Verify that frame_mllp wraps data correctly and unframe_mllp extracts it."""
    raw_message = "MSH|^~\\&|TEST|A|B|C|20261121||ORU^R01|12345|P|2.5.1\r"
    framed = frame_mllp(raw_message)

    assert framed.startswith(MLLP_START_BLOCK)
    assert framed.endswith(MLLP_END_BLOCK)
    assert raw_message.encode("utf-8") in framed

    # Unframe single message
    messages, remainder = unframe_mllp(framed)
    assert len(messages) == 1
    assert messages[0] == raw_message
    assert remainder == b""


def test_mllp_chunked_streaming_and_multiple_messages():
    """Verify that unframe_mllp handles chunked buffers and multiple messages."""
    msg1 = "MSH|^~\\&|APP1|123\r"
    msg2 = "MSH|^~\\&|APP2|456\r"

    stream = frame_mllp(msg1) + frame_mllp(msg2)

    # Chunk 1: first half of stream
    chunk1 = stream[:len(frame_mllp(msg1)) + 5]
    chunk2 = stream[len(frame_mllp(msg1)) + 5:]

    msgs_chunk1, remainder = unframe_mllp(chunk1)
    assert len(msgs_chunk1) == 1
    assert msgs_chunk1[0] == msg1
    assert len(remainder) > 0

    msgs_chunk2, remainder2 = unframe_mllp(remainder + chunk2)
    assert len(msgs_chunk2) == 1
    assert msgs_chunk2[0] == msg2
    assert remainder2 == b""


def test_mllp_oversized_frame_rejected():
    """Verify ValueError is raised if a message exceeds maximum frame size."""
    oversized = "X" * (10 * 1024 * 1024 + 10)
    with pytest.raises(ValueError, match="exceeds maximum permitted MLLP frame limit"):
        frame_mllp(oversized)


def test_generate_hl7_ack_success():
    """Verify ACK generation produces correct MSH and MSA segments with original control ID."""
    ack = generate_hl7_ack(SAMPLE_HL7_ORU, ack_code="AA", text_message="Accepted")
    lines = ack.strip().split("\r")

    assert len(lines) >= 2
    assert lines[0].startswith("MSH|^~\\&|SYNAPSE_LIMS|LIFECARE")
    assert "ACK^R01" in lines[0]

    # MSA segment
    assert lines[1].startswith("MSA|AA|MSG-99001|Accepted")


def test_generate_hl7_ack_error_and_reject():
    """Verify ACK generation handles AE and AR error codes."""
    ack_error = generate_hl7_ack(SAMPLE_HL7_ORU, ack_code="AE", text_message="Syntax error", error_details="Bad PID")
    assert "MSA|AE|MSG-99001|Syntax error: Bad PID" in ack_error

    ack_reject = generate_hl7_ack(SAMPLE_HL7_ORU, ack_code="AR", text_message="Duplicate rejected")
    assert "MSA|AR|MSG-99001|Duplicate rejected" in ack_reject


@pytest.mark.anyio
async def test_mllp_listener_ingestion_and_duplicate_rejection(tmp_path):
    """
    Integration test: Start MLLPListener, transmit HL7 ORU^R01 message,
    verify AA acknowledgement, wallet database persistence, and duplicate rejection.
    """
    db_path = str(tmp_path / "test_mllp_wallet.db")
    storage = WalletStorage(db_path)
    port = get_free_port()

    listener = MLLPListener(host="127.0.0.1", port=port, storage=storage, is_synthetic=True)
    await listener.start()
    assert listener.is_running

    try:
        # 1. Send first message
        ack1 = await send_mllp_message_async(SAMPLE_HL7_ORU, host="127.0.0.1", port=port, timeout=3.0)
        assert "MSA|AA|MSG-99001" in ack1
        assert "accepted and ingested" in ack1

        # Verify wallet stored the patient and report
        patient = storage.get_patient("SYN-9901")
        assert patient is not None
        assert patient.demographics.patient_name == "Aakash Kapoor"
        assert len(patient.reports) == 1
        assert len(patient.reports[0].parameters) == 2

        # 2. Send duplicate message -> should return AR (Application Reject)
        ack2 = await send_mllp_message_async(SAMPLE_HL7_ORU, host="127.0.0.1", port=port, timeout=3.0)
        assert "MSA|AR|MSG-99001" in ack2
        assert "Duplicate report detected" in ack2

        # 3. Send invalid message without MSH -> should return AE (Application Error)
        bad_hl7 = "INVALID|NOT_AN_HL7_MESSAGE\r"
        ack3 = await send_mllp_message_async(bad_hl7, host="127.0.0.1", port=port, timeout=3.0)
        assert "MSA|AE" in ack3

        # Check status statistics
        status = listener.get_status()
        assert status["status"] == "running"
        assert status["stats"]["received"] == 3
        assert status["stats"]["accepted"] == 1
        assert status["stats"]["rejected"] == 2
        assert status["is_synthetic"] is True

    finally:
        await listener.stop()
        assert not listener.is_running
