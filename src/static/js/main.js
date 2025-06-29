
const toggleBtn = document.getElementById('menuToggle');
const bellBtn = document.getElementById('notificationBell');
const mobileNotif = document.getElementById('mobileNotification');
const panel = document.getElementById('notificationPanel');
const mobileMenu = document.getElementById('mobileMenu');
const overlay = document.getElementById('overlay');

function togglePanel() {
    panel.classList.toggle('-translate-x-full');
    overlay.classList.toggle('hidden');
}

toggleBtn.addEventListener('click', () => {
    mobileMenu.classList.toggle('hidden');
});

bellBtn.addEventListener('click', togglePanel);

mobileNotif.addEventListener('click', () => {
    togglePanel();
    mobileMenu.classList.add('hidden');
});

overlay.addEventListener('click', () => {
    panel.classList.add('-translate-x-full');
    overlay.classList.add('hidden');
});

function pollViolations() {
    fetch('/violations')
    .then(response => response.json())
    .then(data => {
        console.log(data)
    });
}

document.addEventListener('DOMContentLoaded', () => {
    // Notification.requestPermission();
    // setInterval(pollViolations, 3000);
});
