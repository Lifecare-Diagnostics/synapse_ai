// ui.js: UI helpers like toast
window.Synapse.ui = {
    showToast: function() {
        const toast = document.getElementById('toast');
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 3000);
    },
    openDrawer: function() {
        alert('Drawer opens');
    }
};

// Global aliases
window.showToast = window.Synapse.ui.showToast;
window.openDrawer = window.Synapse.ui.openDrawer;
