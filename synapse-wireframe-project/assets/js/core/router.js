// router.js: Handles sidebar navigation
window.Synapse.router = {
    nav: function(screenId, el) {
        document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        
        document.getElementById(screenId).classList.add('active');
        if(el) {
            el.classList.add('active');
        } else {
            // Find nav item by onclick matching
            document.querySelectorAll('.nav-item').forEach(n => {
                if(n.getAttribute('onclick') && n.getAttribute('onclick').includes(screenId)) {
                    n.classList.add('active');
                }
            });
        }
    }
};

// Global alias for onclick backwards compatibility
window.nav = function(id) {
    window.Synapse.router.nav(id, window.event ? window.event.currentTarget : null);
};
