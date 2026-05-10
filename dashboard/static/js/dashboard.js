/**
 * AI Security Monitor — Dashboard JavaScript
 * Redesigned: animated counters, uptime, threat breakdown, tech stack status
 */

const socket = io();
const canvas = document.getElementById('video-canvas');
const ctx = canvas.getContext('2d');
const overlay = document.getElementById('video-overlay');
const eventLog = document.getElementById('event-log');
const alertSound = document.getElementById('alert-sound');

// State
let connected = false;
let frameCount = 0;
let lastFpsTime = Date.now();
let localFps = 0;
const MAX_LOG_ITEMS = 50;

// Uptime
const startTime = Date.now();

// Threat breakdown counters
const threatCounts = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 };

// Animated number state
const animatedValues = {};

// ==================== UPTIME COUNTER ====================

function formatUptime(ms) {
    const totalSec = Math.floor(ms / 1000);
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = totalSec % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

setInterval(() => {
    const el = document.getElementById('uptime-value');
    if (el) el.textContent = formatUptime(Date.now() - startTime);
}, 1000);

// ==================== ANIMATED NUMBER COUNTER ====================

function animateNumber(elementId, targetValue) {
    const el = document.getElementById(elementId);
    if (!el) return;

    const current = animatedValues[elementId] || 0;
    const target = parseInt(targetValue) || 0;

    if (current === target) return;

    // Pop animation on the element
    el.classList.remove('updated');
    void el.offsetWidth; // reflow
    el.classList.add('updated');

    const duration = 350;
    const start = performance.now();
    const startVal = current;

    function step(now) {
        const elapsed = now - start;
        const progress = Math.min(elapsed / duration, 1);
        // Ease out cubic
        const eased = 1 - Math.pow(1 - progress, 3);
        const value = Math.round(startVal + (target - startVal) * eased);
        el.textContent = value;
        if (progress < 1) {
            requestAnimationFrame(step);
        } else {
            el.textContent = target;
            animatedValues[elementId] = target;
        }
    }

    animatedValues[elementId] = target;
    requestAnimationFrame(step);
}

// ==================== SOCKET EVENTS ====================

socket.on('connect', () => {
    connected = true;
    updateConnectionStatus(true);
    // Mark Re-ID and Pose as active once connected
    setTechStatus('reid', 'Active', 'ok');
    setTechStatus('pose', 'Active', 'ok');
    console.log('🟢 Connected to server');
});

socket.on('disconnect', () => {
    connected = false;
    updateConnectionStatus(false);
    overlay.classList.remove('hidden');
    setTechStatus('reid', 'Offline', 'err');
    setTechStatus('pose', 'Offline', 'err');
    console.log('🔴 Disconnected');
});

// Video frame
socket.on('video_frame', (data) => {
    if (!data.image) return;

    overlay.classList.add('hidden');
    const img = new Image();
    img.onload = () => {
        canvas.width = img.width;
        canvas.height = img.height;
        ctx.drawImage(img, 0, 0);

        frameCount++;
        const now = Date.now();
        if (now - lastFpsTime >= 1000) {
            localFps = frameCount;
            frameCount = 0;
            lastFpsTime = now;
        }
    };
    img.src = 'data:image/jpeg;base64,' + data.image;
});

// Threat event
socket.on('threat_event', (data) => {
    addEventToLog(data);
    updateThreatBadge(data.threat_level);

    // Update breakdown counts
    const level = (data.threat_level || 'LOW').toUpperCase();
    if (threatCounts.hasOwnProperty(level)) {
        threatCounts[level]++;
        updateThreatBreakdown();
    }

    if (data.threat_level === 'CRITICAL' || data.threat_level === 'HIGH') {
        playAlertSound();
        flashScreen(data.threat_level);
    }
});

// Stats update
socket.on('stats_update', (data) => {
    updateStats(data);
});

// ==================== UI UPDATES ====================

function updateConnectionStatus(isConnected) {
    const dot = document.getElementById('connection-dot');
    const text = document.getElementById('status-text');

    if (isConnected) {
        dot.className = 'status-dot connected';
        text.textContent = 'Live';
        text.style.color = 'var(--accent-green)';
    } else {
        dot.className = 'status-dot error';
        text.textContent = 'Offline';
        text.style.color = 'var(--accent-red)';
    }
}

function setTechStatus(type, label, statusClass) {
    const statusEl = document.getElementById(`${type}-dot`);
    const labelEl = document.getElementById(`${type}-status`);
    if (statusEl) {
        statusEl.className = `tech-status ${statusClass}`;
    }
    if (labelEl) {
        labelEl.textContent = label;
    }
}

function updateStats(data) {
    if (data.tracking) {
        animateNumber('active-persons', data.tracking.active_persons || 0);
        animateNumber('active-weapons', data.tracking.active_weapons || 0);

        // Re-ID count (use unique_persons or gallery_size if available)
        const reidCount = data.tracking.unique_persons || data.tracking.reid_count || data.tracking.total_persons || 0;
        animateNumber('reid-count', reidCount);

        // Highlight weapons card
        const weaponCard = document.getElementById('card-weapons');
        if (data.tracking.active_weapons > 0) {
            weaponCard.style.borderColor = 'var(--accent-critical)';
            weaponCard.style.boxShadow = 'var(--glow-red)';
        } else {
            weaponCard.style.borderColor = '';
            weaponCard.style.boxShadow = '';
        }

        // Update Re-ID tech status
        if (data.tracking.reid_enabled !== undefined) {
            setTechStatus('reid', data.tracking.reid_enabled ? 'Active' : 'Disabled',
                data.tracking.reid_enabled ? 'ok' : 'warn');
        }
        if (data.tracking.pose_enabled !== undefined) {
            setTechStatus('pose', data.tracking.pose_enabled ? 'Active' : 'Disabled',
                data.tracking.pose_enabled ? 'ok' : 'warn');
        }
    }

    if (data.threat) {
        animateNumber('total-alerts', data.threat.total_events || 0);
        updateThreatBadge(data.threat.current_threat_level);

        // Sync breakdown if server provides breakdown data
        if (data.threat.breakdown) {
            const b = data.threat.breakdown;
            threatCounts.CRITICAL = b.critical || threatCounts.CRITICAL;
            threatCounts.HIGH = b.high || threatCounts.HIGH;
            threatCounts.MEDIUM = b.medium || threatCounts.MEDIUM;
            threatCounts.LOW = b.low || threatCounts.LOW;
            updateThreatBreakdown();
        }
    }

    const fps = data.fps || localFps;
    animateNumber('fps-value', fps);

    if (data.source) {
        const el = document.getElementById('source-label');
        if (el) el.textContent = data.source;
    }
}

function updateThreatBadge(level) {
    const badge = document.getElementById('threat-badge');
    const text = document.getElementById('threat-text');

    badge.className = 'threat-badge';
    if (level) {
        badge.classList.add(level.toLowerCase());
        text.textContent = level;
    }
}

function updateThreatBreakdown() {
    const total = threatCounts.CRITICAL + threatCounts.HIGH + threatCounts.MEDIUM + threatCounts.LOW;
    const totalEl = document.getElementById('breakdown-total');
    if (totalEl) totalEl.textContent = `${total} event${total !== 1 ? 's' : ''}`;

    const countCritical = document.getElementById('count-critical');
    const countHigh = document.getElementById('count-high');
    const countMedium = document.getElementById('count-medium');
    if (countCritical) countCritical.textContent = threatCounts.CRITICAL;
    if (countHigh) countHigh.textContent = threatCounts.HIGH;
    if (countMedium) countMedium.textContent = threatCounts.MEDIUM;

    if (total === 0) {
        setBarWidth('bar-critical', 0);
        setBarWidth('bar-high', 0);
        setBarWidth('bar-medium', 0);
        setBarWidth('bar-low', 100);
        return;
    }

    const critPct = (threatCounts.CRITICAL / total) * 100;
    const highPct = (threatCounts.HIGH / total) * 100;
    const medPct = (threatCounts.MEDIUM / total) * 100;
    const lowPct = Math.max(0, 100 - critPct - highPct - medPct);

    setBarWidth('bar-critical', critPct);
    setBarWidth('bar-high', highPct);
    setBarWidth('bar-medium', medPct);
    setBarWidth('bar-low', lowPct);
}

function setBarWidth(id, pct) {
    const el = document.getElementById(id);
    if (el) el.style.width = pct + '%';
}

function addEventToLog(event) {
    const log = document.getElementById('event-log');

    // Remove empty state
    const empty = log.querySelector('.event-empty');
    if (empty) empty.remove();

    const item = document.createElement('div');
    const level = (event.threat_level || 'LOW').toLowerCase();
    item.className = `event-item ${level} new`;

    const timestamp = event.timestamp
        ? new Date(event.timestamp * 1000).toLocaleTimeString('vi-VN')
        : new Date().toLocaleTimeString('vi-VN');

    item.innerHTML = `
        <div class="event-header">
            <span class="event-level ${level}">${(event.threat_level || 'LOW').toUpperCase()}</span>
            <span class="event-time">${timestamp}</span>
        </div>
        <div class="event-desc">${event.description || 'Unknown event'}</div>
    `;

    log.insertBefore(item, log.firstChild);

    while (log.children.length > MAX_LOG_ITEMS) {
        log.removeChild(log.lastChild);
    }

    setTimeout(() => item.classList.remove('new'), 3000);
}

function playAlertSound() {
    try {
        if (alertSound) {
            alertSound.currentTime = 0;
            alertSound.play().catch(() => { });
        }
    } catch (e) { }
}

function flashScreen(level) {
    const color = level === 'CRITICAL'
        ? 'rgba(255, 45, 85, 0.1)'
        : 'rgba(251, 146, 60, 0.08)';

    const flash = document.createElement('div');
    flash.style.cssText = `
        position: fixed; inset: 0; z-index: 999;
        background: ${color};
        pointer-events: none;
        animation: fadeOut 1s ease-out forwards;
    `;
    document.body.appendChild(flash);
    setTimeout(() => flash.remove(), 1000);
}

// ==================== CLEAR LOG ====================

document.getElementById('btn-clear-log').addEventListener('click', () => {
    eventLog.innerHTML = `
        <div class="event-empty">
            <span>🔒</span>
            <p>Log cleared — Hệ thống đang giám sát</p>
        </div>
    `;
});

// ==================== POLL STATS ====================

setInterval(() => {
    if (!connected) return;
    fetch('/api/stats')
        .then(r => r.json())
        .then(data => updateStats(data))
        .catch(() => { });
}, 2000);

// ==================== STYLE INJECTION ====================

const fadeStyle = document.createElement('style');
fadeStyle.textContent = `
    @keyframes fadeOut {
        from { opacity: 1; }
        to { opacity: 0; }
    }
`;
document.head.appendChild(fadeStyle);

console.log('🛡️ AI Security Monitor Dashboard v2 loaded');