// upload.js: Logic for Upload screen
window.Synapse.screens.upload = {
    simulate: function() {
        const list = document.getElementById('upload-list');
        list.style.display = 'block';
        const text = list.querySelector('.progress-text');
        
        const steps = [
            "Uploaded",
            "Format detected: Digital PDF",
            "Text extracted",
            "Fields extracted",
            "Awaiting validation"
        ];
        
        let i = 0;
        const interval = setInterval(() => {
            if(i < steps.length) {
                text.innerText = steps[i];
                if (i === steps.length - 1) {
                    text.style.color = "var(--amber)";
                    text.style.fontWeight = "bold";
                }
                i++;
            } else {
                clearInterval(interval);
            }
        }, 800);
    },
    render: function(container) {},
    init: function() {}
};

// Global alias
window.simulateUpload = window.Synapse.screens.upload.simulate;
