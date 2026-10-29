// annotations.js: Handles toggling annotations
window.Synapse.annotations = {
    toggle: function() {
        document.body.classList.toggle('annotations-on');
    }
};

// Global alias
window.toggleAnnotations = window.Synapse.annotations.toggle;
