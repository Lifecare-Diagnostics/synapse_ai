"""
synapse_poc/synapse/mllp.py
Minimal Lower Layer Protocol (MLLP) Framing, Listener, and Client Architecture.
Implements standard HL7 framing (VT \\x0b, FS \\x1c, CR \\x0d) over TCP/TLS with
payload size limits, automatic HL7 acknowledgement generation (ACK^R01 / MSA),
and integration with Synapse Wallet Storage.
"""

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import re
import ssl
from typing import Any, Callable, Dict, List, Optional, Tuple

from synapse.fhir import parse_hl7_v2_oru_r01, record_interop_audit
from synapse.storage import WalletStorage

logger = logging.getLogger("synapse.mllp")

MLLP_START_BLOCK = b"\x0b"       # 0x0B (VT)
MLLP_END_BLOCK = b"\x1c\x0d"     # 0x1C 0x0D (FS CR)
MAX_MLLP_MESSAGE_SIZE = 10 * 1024 * 1024  # 10 MB maximum payload guard


# ---------------------------------------------------------------------------
# Framing & Unframing Primitives
# ---------------------------------------------------------------------------

def frame_mllp(hl7_message: str) -> bytes:
    """
    Wrap an HL7 pipe-delimited message string inside standard MLLP framing.
    Format: <VT> <HL7-Message> <FS> <CR>
    """
    content = hl7_message.encode("utf-8")
    if len(content) > MAX_MLLP_MESSAGE_SIZE:
        raise ValueError(
            f"Message size ({len(content)} bytes) exceeds maximum permitted MLLP frame limit of {MAX_MLLP_MESSAGE_SIZE} bytes."
        )
    return MLLP_START_BLOCK + content + MLLP_END_BLOCK


def unframe_mllp(buffer: bytes) -> Tuple[List[str], bytes]:
    """
    Extract complete HL7 messages from buffered bytes received over TCP socket.
    Returns:
        (extracted_messages, remaining_buffer)
    Raises:
        ValueError if buffer contains an oversized unclosed frame.
    """
    messages: List[str] = []
    current = buffer

    while True:
        start_idx = current.find(MLLP_START_BLOCK)
        if start_idx == -1:
            # No start block found; if buffer is too large without start block, discard to prevent memory exhaustion
            if len(current) > MAX_MLLP_MESSAGE_SIZE:
                current = b""
            break

        end_idx = current.find(MLLP_END_BLOCK, start_idx + 1)
        if end_idx == -1:
            # Incomplete frame; check size guard
            if len(current) - start_idx > MAX_MLLP_MESSAGE_SIZE:
                raise ValueError("MLLP frame exceeded maximum permitted buffer size without end block.")
            break

        # Extract payload between start block and end block
        payload_bytes = current[start_idx + 1:end_idx]
        try:
            msg_str = payload_bytes.decode("utf-8")
        except UnicodeDecodeError:
            msg_str = payload_bytes.decode("latin-1")
        messages.append(msg_str)

        # Advance current buffer past end block
        current = current[end_idx + 2:]

    return messages, current


# ---------------------------------------------------------------------------
# HL7 Acknowledgement (ACK) Generator
# ---------------------------------------------------------------------------

def generate_hl7_ack(
    original_hl7: str,
    ack_code: str = "AA",  # AA = Application Accept, AE = Application Error, AR = Application Reject
    text_message: str = "Message accepted and processed",
    error_details: Optional[str] = None,
    sending_app: str = "SYNAPSE_LIMS",
    sending_facility: str = "LIFECARE",
) -> str:
    """
    Generate an HL7 v2.5.1 ACK message responding to the incoming message's MSH header.
    Extracts MSH-10 (Message Control ID) to correlate the response in MSA-2.
    """
    lines = [l.strip() for l in original_hl7.replace("\r", "\n").split("\n") if l.strip()]
    msh_fields: List[str] = []
    for line in lines:
        if line.startswith("MSH"):
            msh_fields = line.split("|")
            break

    # Extract original control ID (MSH-10) and sending entity (MSH-3 / MSH-4)
    orig_control_id = msh_fields[9] if len(msh_fields) > 9 else "UNKNOWN"
    recv_app = msh_fields[2] if len(msh_fields) > 2 else "EXTERNAL_SYSTEM"
    recv_facility = msh_fields[3] if len(msh_fields) > 3 else "HOSPITAL"

    now_ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    ack_control_id = f"ACK_{now_ts}_{orig_control_id[:12]}"

    ack_msh = (
        f"MSH|^~\\&|{sending_app}|{sending_facility}|{recv_app}|{recv_facility}|"
        f"{now_ts}||ACK^R01|{ack_control_id}|P|2.5.1"
    )

    msg_text = text_message
    if error_details:
        msg_text = f"{text_message}: {error_details}"

    ack_msa = f"MSA|{ack_code}|{orig_control_id}|{msg_text}"
    return f"{ack_msh}\r{ack_msa}\r"


# ---------------------------------------------------------------------------
# Asynchronous MLLP Listener Service
# ---------------------------------------------------------------------------

class MLLPListener:
    """
    Asyncio TCP Server receiving HL7 messages wrapped in MLLP framing.
    Integrates with Synapse Wallet Storage, duplicate detection, and audit logging.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 2575,
        storage: Optional[WalletStorage] = None,
        ssl_context: Optional[ssl.SSLContext] = None,
        is_synthetic: bool = True,
    ):
        self.host = host
        self.port = port
        self.storage = storage
        self.ssl_context = ssl_context
        self.is_synthetic = is_synthetic
        self._server: Optional[asyncio.Server] = None
        self._messages_received = 0
        self._messages_accepted = 0
        self._messages_rejected = 0
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running and self._server is not None

    def get_status(self) -> Dict[str, Any]:
        """Return runtime status and configuration of the MLLP service."""
        return {
            "status": "running" if self.is_running else "stopped",
            "host": self.host,
            "port": self.port,
            "tls_enabled": self.ssl_context is not None,
            "connection_mode": "mllp_simulated_listener" if self.is_synthetic else "mllp_live_listener",
            "is_synthetic": self.is_synthetic,
            "stats": {
                "received": self._messages_received,
                "accepted": self._messages_accepted,
                "rejected": self._messages_rejected,
            },
        }

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle individual TCP client connection over MLLP protocol."""
        buffer = b""
        peer_name = writer.get_extra_info("peername")
        logger.info(f"MLLP client connected from {peer_name}")

        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break

                buffer += data
                try:
                    messages, buffer = unframe_mllp(buffer)
                except ValueError as ve:
                    logger.error(f"MLLP framing violation from {peer_name}: {ve}")
                    err_ack = generate_hl7_ack(
                        "MSH|^~\\&|CLIENT",
                        ack_code="AE",
                        text_message="Framing violation",
                        error_details=str(ve),
                    )
                    writer.write(frame_mllp(err_ack))
                    await writer.drain()
                    break

                for msg in messages:
                    self._messages_received += 1
                    ack = self._process_hl7_message(msg)
                    writer.write(frame_mllp(ack))
                    await writer.drain()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error handling MLLP client {peer_name}: {e}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    def _process_hl7_message(self, hl7_text: str) -> str:
        """
        Process a single unframed HL7 message: validate, parse, save, audit,
        and generate the appropriate ACK.
        """
        try:
            parsed = parse_hl7_v2_oru_r01(hl7_text)
        except Exception as e:
            self._messages_rejected += 1
            record_interop_audit(
                action="mllp_ingest_error",
                format_type="HL7_v2_MLLP",
                resource_count=0,
                status="failure",
                details=f"Parse failure: {str(e)}",
            )
            return generate_hl7_ack(
                hl7_text,
                ack_code="AE",
                text_message="HL7 parsing failed",
                error_details=str(e),
            )

        patient_id = parsed["patient_id"]
        report_id = parsed["report_id"]
        content_hash = hashlib.sha256(hl7_text.encode("utf-8")).hexdigest()

        if self.storage:
            dup = self.storage.find_duplicate_report(patient_id, f"{report_id}.hl7", content_hash=content_hash)
            if dup:
                self._messages_rejected += 1
                record_interop_audit(
                    action="mllp_duplicate_detected",
                    format_type="HL7_v2_MLLP",
                    resource_count=0,
                    status="rejected",
                    identifier=report_id,
                    details=f"Duplicate report ID {report_id} for patient {patient_id}",
                )
                return generate_hl7_ack(
                    hl7_text,
                    ack_code="AR",
                    text_message="Duplicate report detected",
                    error_details=f"Report '{report_id}' already ingested for patient '{patient_id}'",
                )

            # Ingest demographics
            demographics = parsed.get("demographics")
            if demographics:
                self.storage.save_patient(demographics)

            # Ingest report
            api_payload = {
                "patient_id": patient_id,
                "report_id": report_id,
                "report_date": parsed["report_date"],
                "report_category": parsed["report_category"],
                "parameters": parsed["parameters"],
                "notes": json.dumps(parsed.get("key_text_sections", {})),
            }
            self.storage.ingest_api_json_record(api_payload, content_hash=content_hash)

        self._messages_accepted += 1
        record_interop_audit(
            action="mllp_ingest_success",
            format_type="HL7_v2_MLLP",
            resource_count=len(parsed.get("parameters", [])),
            status="success",
            identifier=report_id,
            details=f"Ingested {len(parsed.get('parameters', []))} parameters via MLLP",
        )
        return generate_hl7_ack(
            hl7_text,
            ack_code="AA",
            text_message="Report accepted and ingested successfully",
        )

    async def start(self) -> None:
        """Start listening for MLLP TCP connections."""
        if self._is_running:
            return
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self.host,
            port=self.port,
            ssl=self.ssl_context,
        )
        self._is_running = True
        logger.info(f"MLLP listener active on {self.host}:{self.port} (TLS: {self.ssl_context is not None})")

    async def stop(self) -> None:
        """Stop listening and terminate server."""
        if not self._is_running or not self._server:
            return
        self._server.close()
        await self._server.wait_closed()
        self._is_running = False
        logger.info("MLLP listener stopped")


# ---------------------------------------------------------------------------
# Client Helpers for Testing & Gateway Transmission
# ---------------------------------------------------------------------------

async def send_mllp_message_async(
    hl7_message: str,
    host: str = "127.0.0.1",
    port: int = 2575,
    ssl_context: Optional[ssl.SSLContext] = None,
    timeout: float = 5.0,
) -> str:
    """
    Connect to an MLLP server asynchronously, send an MLLP-framed HL7 message,
    and return the unframed ACK response string.
    """
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host=host, port=port, ssl=ssl_context),
        timeout=timeout,
    )
    try:
        framed = frame_mllp(hl7_message)
        writer.write(framed)
        await writer.drain()

        buffer = b""
        while True:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=timeout)
            if not chunk:
                break
            buffer += chunk
            messages, buffer = unframe_mllp(buffer)
            if messages:
                return messages[0]
        raise RuntimeError("Connection closed without receiving complete MLLP ACK frame.")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


def send_mllp_message(
    hl7_message: str,
    host: str = "127.0.0.1",
    port: int = 2575,
    ssl_context: Optional[ssl.SSLContext] = None,
    timeout: float = 5.0,
) -> str:
    """Synchronous convenience wrapper around send_mllp_message_async."""
    return asyncio.run(send_mllp_message_async(hl7_message, host=host, port=port, ssl_context=ssl_context, timeout=timeout))
