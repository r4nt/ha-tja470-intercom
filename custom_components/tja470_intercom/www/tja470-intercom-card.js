class TJA470IntercomCard extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._config = null;
    this._confirmUnlock = false;
    this._confirmTimeout = null;
    this._confirmUnlockMini = {};
    this._confirmTimeoutMini = {};
    this._showPassword = false;
    this._elements = {};
    this._currentToken = null;
    this._currentEntityId = null;
    this._drawerOpen = false;
  }

  setConfig(config) {
    if (config.entity && !config.entity.startsWith('camera.')) {
      throw new Error('The entity must be a camera entity.');
    }
    this._config = config;
  }

  set hass(hass) {
    this._hass = hass;
    
    // Resolve camera entity ID
    let entityId = this._config && this._config.entity;
    if (!entityId || !hass.states[entityId]) {
      // Auto-discover the first Hager TJA470 camera entity if not specified or not found
      const foundEntity = Object.keys(hass.states).find(key => 
        key.startsWith('camera.tja470_intercom_controller_') && key.endsWith('_camera')
      );
      if (foundEntity) {
        entityId = foundEntity;
      }
    }

    if (!entityId) {
      this._renderError('Hager TJA470 Intercom camera entity not found.');
      return;
    }

    const stateObj = hass.states[entityId];
    if (!stateObj) {
      this._renderError(`Entity not found: ${entityId}`);
      return;
    }

    this._resolvedEntityId = entityId;

    if (!this.shadowRoot) {
      this._firstRender(stateObj);
    } else {
      this._updateCard(stateObj);
    }
  }

  getCardSize() {
    return 5;
  }

  // Safe DOM Element Creator (XSS Free)
  _el(tag, attrs = {}, children = []) {
    const el = document.createElement(tag);
    for (const [key, val] of Object.entries(attrs)) {
      if (key === 'style' && typeof val === 'object') {
        Object.assign(el.style, val);
      } else if (key.startsWith('on') && typeof val === 'function') {
        const eventName = key.slice(2).toLowerCase();
        el.addEventListener(eventName, val);
      } else {
        el.setAttribute(key, val);
      }
    }
    for (const child of children) {
      if (typeof child === 'string') {
        el.appendChild(document.createTextNode(child));
      } else if (child instanceof Element || child instanceof DocumentFragment) {
        el.appendChild(child);
      }
    }
    return el;
  }

  // Safe SVG Parser (XSS Free)
  _svg(markup) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(markup, 'image/svg+xml');
    return doc.documentElement;
  }

  _renderError(message) {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: 'open' });
    }
    const errorCard = this._el('ha-card', { class: 'error-card' }, [
      this._el('div', { style: { padding: '16px', color: '#ef4444', fontWeight: 'bold' } }, [
        message
      ])
    ]);
    this.shadowRoot.replaceChildren(errorCard);
  }

  _firstRender(stateObj) {
    this.attachShadow({ mode: 'open' });

    // Stylesheet
    const style = document.createElement('style');
    style.textContent = `
      :host {
        display: block;
      }
      ha-card {
        background: var(--ha-card-background, var(--card-background-color, #1c1c1e));
        border-radius: var(--ha-card-border-radius, 16px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        box-shadow: var(--ha-card-box-shadow, 0 8px 24px rgba(0, 0, 0, 0.15));
        overflow: hidden;
        font-family: var(--paper-font-body1_-_font-family, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif);
        color: var(--primary-text-color, #ffffff);
        position: relative;
      }
      .card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 20px;
      }
      .card-title {
        font-size: 1.15rem;
        font-weight: 600;
        margin: 0;
        letter-spacing: -0.3px;
      }
      .status-indicator {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 0.8rem;
        color: var(--secondary-text-color, #8e8e93);
      }
      .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background-color: hsl(120, 80%, 40%);
        box-shadow: 0 0 8px hsl(120, 80%, 45%);
        transition: all 0.3s ease;
      }
      .status-dot.offline {
        background-color: hsl(0, 80%, 50%);
        box-shadow: 0 0 8px hsl(0, 80%, 55%);
      }
      .video-container {
        position: relative;
        width: calc(100% - 32px);
        margin: 0 auto;
        aspect-ratio: 16 / 9;
        border-radius: 12px;
        background-color: #000000;
        overflow: hidden;
        box-shadow: inset 0 0 20px rgba(0,0,0,0.8), 0 4px 12px rgba(0,0,0,0.2);
      }
      .video-stream {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
      }
      .video-overlay-live {
        position: absolute;
        top: 12px;
        left: 12px;
        background: rgba(239, 68, 68, 0.85);
        color: #fff;
        font-size: 0.65rem;
        font-weight: 700;
        letter-spacing: 0.5px;
        padding: 3px 8px;
        border-radius: 4px;
        text-transform: uppercase;
        display: flex;
        align-items: center;
        gap: 5px;
        backdrop-filter: blur(4px);
        z-index: 2;
      }
      .video-overlay-live .pulse-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background-color: #fff;
        animation: pulse 1.5s infinite;
      }
      .video-overlay-title {
        position: absolute;
        bottom: 12px;
        left: 12px;
        background: rgba(0, 0, 0, 0.6);
        color: #fff;
        font-size: 0.8rem;
        font-weight: 500;
        padding: 4px 10px;
        border-radius: 6px;
        backdrop-filter: blur(4px);
        z-index: 2;
      }
      .loader {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        display: flex;
        justify-content: center;
        align-items: center;
        background: rgba(0, 0, 0, 0.6);
        z-index: 1;
        transition: opacity 0.3s ease;
      }
      .loader.hidden {
        opacity: 0;
        pointer-events: none;
      }
      .spinner {
        width: 28px;
        height: 28px;
        border: 3px solid rgba(255, 255, 255, 0.2);
        border-radius: 50%;
        border-top-color: #fff;
        animation: spin 1s ease-in-out infinite;
      }
      .controls {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
        padding: 16px;
      }
      .btn {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        padding: 12px 16px;
        border-radius: 10px;
        font-size: 0.9rem;
        font-weight: 600;
        border: none;
        cursor: pointer;
        outline: none;
        transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
        user-select: none;
      }
      .btn-unlock {
        background: linear-gradient(135deg, hsl(38, 100%, 43%), hsl(43, 100%, 48%));
        color: #ffffff;
        box-shadow: 0 4px 14px rgba(217, 119, 6, 0.25);
      }
      .btn-unlock:hover:not(.disabled) {
        transform: translateY(-2px);
        box-shadow: 0 6px 18px rgba(217, 119, 6, 0.35);
      }
      .btn-unlock:active:not(.disabled) {
        transform: translateY(0);
      }
      .btn-unlock.confirm {
        background: linear-gradient(135deg, hsl(4, 90%, 55%), hsl(0, 85%, 58%));
        box-shadow: 0 4px 14px rgba(220, 38, 38, 0.3);
        animation: shake 0.4s ease-in-out;
      }
      .btn-unlock.disabled {
        background: #2c2c2e;
        color: #8e8e93;
        box-shadow: none;
        cursor: not-allowed;
        opacity: 0.5;
        transform: none;
      }
      .btn-switch {
        background: linear-gradient(135deg, hsl(210, 80%, 43%), hsl(195, 80%, 43%));
        color: #ffffff;
        box-shadow: 0 4px 14px rgba(2, 132, 199, 0.25);
      }
      .btn-switch:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 18px rgba(2, 132, 199, 0.35);
      }
      .btn-switch:active {
        transform: translateY(0);
      }
      .btn-icon {
        width: 18px;
        height: 18px;
        fill: currentColor;
      }
      .extra-doors {
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 0 16px 16px 16px;
      }
      .extra-door-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 8px;
        padding: 8px 12px;
      }
      .extra-door-name {
        font-size: 0.85rem;
        font-weight: 500;
      }
      .btn-mini-unlock {
        padding: 6px 12px;
        font-size: 0.75rem;
        border-radius: 6px;
        font-weight: 600;
        border: none;
        background: rgba(255, 255, 255, 0.1);
        color: #fff;
        cursor: pointer;
        transition: all 0.2s ease;
        user-select: none;
      }
      .btn-mini-unlock:hover {
        background: linear-gradient(135deg, hsl(38, 100%, 43%), hsl(43, 100%, 48%));
        box-shadow: 0 2px 8px rgba(217, 119, 6, 0.2);
      }
      .btn-mini-unlock.confirm {
        background: linear-gradient(135deg, hsl(4, 90%, 55%), hsl(0, 85%, 58%));
        animation: shake 0.4s ease-in-out;
      }
      .drawer {
        border-top: 1px solid rgba(255, 255, 255, 0.06);
      }
      .drawer-toggle {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 20px;
        cursor: pointer;
        font-size: 0.8rem;
        font-weight: 600;
        color: var(--secondary-text-color, #8e8e93);
        user-select: none;
        transition: color 0.2s ease;
      }
      .drawer-toggle:hover {
        color: var(--primary-text-color, #ffffff);
      }
      .drawer-toggle-icon {
        width: 14px;
        height: 14px;
        fill: currentColor;
        transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
      }
      .drawer-toggle.open .drawer-toggle-icon {
        transform: rotate(180deg);
      }
      .drawer-content {
        display: none;
        padding: 0 20px 20px 20px;
      }
      .drawer-content.open {
        display: block;
      }
      .info-grid {
        display: grid;
        grid-template-columns: 1fr;
        gap: 8px;
      }
      .info-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.04);
        border-radius: 8px;
        padding: 8px 12px;
      }
      .info-label {
        font-size: 0.75rem;
        color: var(--secondary-text-color, #8e8e93);
      }
      .info-value-container {
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .info-value {
        font-size: 0.8rem;
        font-family: monospace;
        font-weight: 500;
        word-break: break-all;
      }
      .copy-btn {
        background: none;
        border: none;
        color: var(--secondary-text-color, #8e8e93);
        cursor: pointer;
        padding: 4px;
        display: flex;
        align-items: center;
        border-radius: 4px;
        transition: all 0.2s ease;
      }
      .copy-btn:hover {
        color: var(--primary-text-color, #ffffff);
        background: rgba(255, 255, 255, 0.05);
      }
      .copy-btn-icon {
        width: 14px;
        height: 14px;
        fill: currentColor;
      }
      .toast {
        position: absolute;
        bottom: 20px;
        left: 50%;
        transform: translateX(-50%) translateY(100px);
        background: rgba(0, 0, 0, 0.85);
        color: #fff;
        font-size: 0.75rem;
        font-weight: 600;
        padding: 8px 16px;
        border-radius: 20px;
        z-index: 10;
        transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        pointer-events: none;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        border: 1px solid rgba(255, 255, 255, 0.1);
        text-align: center;
        white-space: nowrap;
      }
      .toast.show {
        transform: translateX(-50%) translateY(0);
      }
      @keyframes pulse {
        0% { transform: scale(0.9); opacity: 0.6; }
        50% { transform: scale(1.1); opacity: 1; }
        100% { transform: scale(0.9); opacity: 0.6; }
      }
      @keyframes spin {
        to { transform: rotate(360deg); }
      }
      @keyframes shake {
        0%, 100% { transform: translateX(0); }
        20%, 60% { transform: translateX(-4px); }
        40%, 80% { transform: translateX(4px); }
      }
    `;
    this.shadowRoot.appendChild(style);

    // Create DOM structure
    const titleTextNode = document.createTextNode(this._config.name || stateObj.attributes.friendly_name || 'Intercom');
    const statusTextNode = document.createTextNode('Connecting');
    
    this._elements.statusDot = this._el('div', { class: 'status-dot offline' });
    this._elements.statusText = statusTextNode;
    
    const header = this._el('div', { class: 'card-header' }, [
      this._el('h2', { class: 'card-title' }, [titleTextNode]),
      this._el('div', { class: 'status-indicator' }, [
        this._elements.statusDot,
        this._el('span', {}, [statusTextNode])
      ])
    ]);

    // Stream Container Elements
    const imgEl = this._el('img', {
      class: 'video-stream',
      alt: 'Camera feed loading...',
      onload: () => this._elements.loader.classList.add('hidden'),
      onerror: () => this._elements.loader.classList.add('hidden')
    });
    this._elements.img = imgEl;

    this._elements.loader = this._el('div', { class: 'loader' }, [
      this._el('div', { class: 'spinner' })
    ]);

    this._elements.liveTitle = document.createTextNode('Stream Inactive');
    
    const streamContainer = this._el('div', { class: 'video-container' }, [
      this._el('div', { class: 'video-overlay-live' }, [
        this._el('div', { class: 'pulse-dot' }),
        'Live'
      ]),
      this._el('div', { class: 'video-overlay-title' }, [
        this._elements.liveTitle
      ]),
      this._elements.loader,
      imgEl
    ]);

    // Main Control Buttons
    this._elements.unlockBtnText = document.createTextNode('Unlock Door');
    this._elements.unlockBtnIconContainer = this._el('span', {}, [
      this._svg('<svg class="btn-icon" viewBox="0 0 24 24"><path d="M12,17A2,2 0 0,0 14,15C14,13.89 13.11,13 12,13A2,2 0 0,0 10,15A2,2 0 0,0 12,17M18,8A2,2 0 0,1 20,10V20A2,2 0 0,1 18,22H6A2,2 0 0,1 4,20V10C4,8.89 4.9,8 6,8H7V6A5,5 0 0,1 12,1A5,5 0 0,1 17,6V8H18M12,3A3,3 0 0,0 9,6V8H15V6A3,3 0 0,0 12,3Z"/></svg>')
    ]);

    const unlockBtn = this._el('button', {
      class: 'btn btn-unlock',
      onclick: () => this._handleUnlock()
    }, [
      this._elements.unlockBtnIconContainer,
      this._el('span', {}, [this._elements.unlockBtnText])
    ]);
    this._elements.unlockBtn = unlockBtn;

    const switchBtn = this._el('button', {
      class: 'btn btn-switch',
      onclick: () => this._handleSwitch()
    }, [
      this._svg('<svg class="btn-icon" viewBox="0 0 24 24"><path d="M20 4H16.82L15 2H9L7.18 4H4C2.9 4 2 4.9 2 6V18C2 19.1 2.9 20 4 20H20C21.1 20 22 19.1 22 18V6C22 4.9 21.1 4 20 4M20 18H4V6H8.05L9.87 4H14.13L15.95 6H20V18M12 7C9.24 7 7 9.24 7 12S9.24 17 12 17 17 14.76 17 12 14.76 7 12 7M12 15C10.35 15 9 13.65 9 12S10.35 9 12 9 15 10.35 15 12 13.65 15 12 15Z"/></svg>'),
      this._el('span', {}, ['Switch Feed'])
    ]);
    this._elements.switchBtn = switchBtn;

    const controls = this._el('div', { class: 'controls' }, [
      unlockBtn,
      switchBtn
    ]);

    // Extra Door Stations
    this._elements.extraDoors = this._el('div', { class: 'extra-doors' });

    // Technical Details Drawer
    const chevronIcon = this._svg('<svg class="drawer-toggle-icon" viewBox="0 0 24 24"><path d="M7.41,8.58L12,13.17L16.59,8.58L18,10L12,16L6,10L7.41,8.58Z"/></svg>');
    const drawerToggle = this._el('div', {
      class: 'drawer-toggle',
      onclick: () => this._toggleDrawer()
    }, [
      this._el('span', {}, ['Technical Details']),
      chevronIcon
    ]);
    this._elements.drawerToggle = drawerToggle;

    this._elements.sipUsername = document.createTextNode('-');
    this._elements.sipPassword = document.createTextNode('••••••••');
    this._elements.sipRegistrar = document.createTextNode('-');
    this._elements.stunServer = document.createTextNode('-');
    this._elements.webrtcPort = document.createTextNode('-');

    // Eye Icons
    this._elements.eyeIconContainer = this._el('span', {
      class: 'copy-btn',
      style: { display: 'inline-flex', padding: '2px' },
      onclick: (e) => this._togglePasswordVisibility(e)
    }, [this._getEyeIcon()]);

    const drawerContent = this._el('div', { class: 'drawer-content' }, [
      this._el('div', { class: 'info-grid' }, [
        this._createInfoRow('SIP ID / User', this._elements.sipUsername, true),
        this._createInfoRow('SIP Password', this._elements.sipPassword, true, this._elements.eyeIconContainer),
        this._createInfoRow('SIP Registrar', this._elements.sipRegistrar, true),
        this._createInfoRow('STUN Relay Host', this._elements.stunServer, true),
        this._createInfoRow('WebRTC WS Port', this._elements.webrtcPort, false)
      ])
    ]);
    this._elements.drawerContent = drawerContent;

    const drawer = this._el('div', { class: 'drawer' }, [
      drawerToggle,
      drawerContent
    ]);

    // Toast Alert
    this._elements.toast = this._el('div', { class: 'toast' }, ['Copied!']);

    // Assemble ha-card
    const card = this._el('ha-card', {}, [
      header,
      streamContainer,
      controls,
      this._elements.extraDoors,
      drawer,
      this._elements.toast
    ]);

    this.shadowRoot.appendChild(card);
    
    // Initial data load
    this._updateCard(stateObj);
  }

  _createInfoRow(label, textNode, canCopy, extraControl = null) {
    const valueSpan = this._el('span', { class: 'info-value' }, [textNode]);
    const rowChildren = [valueSpan];

    if (extraControl) {
      rowChildren.push(extraControl);
    }

    if (canCopy) {
      const copyBtn = this._el('button', {
        class: 'copy-btn',
        title: 'Copy value',
        onclick: () => this._copyValue(textNode.nodeValue)
      }, [
        this._svg('<svg class="copy-btn-icon" viewBox="0 0 24 24"><path d="M19,21H8V7H19M19,5H8A2,2 0 0,0 6,7V21A2,2 0 0,0 8,23H19A2,2 0 0,0 21,21V7A2,2 0 0,0 19,5M16,1H4A2,2 0 0,0 2,3V17H4V3H16V1Z"/></svg>')
      ]);
      rowChildren.push(copyBtn);
    }

    return this._el('div', { class: 'info-row' }, [
      this._el('span', { class: 'info-label' }, [label]),
      this._el('div', { class: 'info-value-container' }, rowChildren)
    ]);
  }

  _getEyeIcon() {
    if (this._showPassword) {
      return this._svg('<svg class="btn-icon" viewBox="0 0 24 24" style="width:16px;height:16px;"><path d="M2,4.27L5.27,7.54C3.25,8.81 1.62,10.59 0.5,12.5C1.88,14.88 4.71,16.5 8,16.5C8.88,16.5 9.73,16.39 10.55,16.19L13.82,19.46L15.09,18.19L3.27,3L2,4.27ZM12,17A5,5 0 0,1 7,12C7,11.38 7.12,10.78 7.33,10.24L10.24,13.15C10.78,13.88 11.38,14 12,14A5,5 0 0,1 12,17M12,9A3,3 0 0,0 9,12C9,12.06 9.05,12.11 9.05,12.16L11.84,9.37C11.3,9.15 10.7,9 10,9M12,4.5C17,4.5 21.27,7.61 23,12C21.82,14.7 19.82,16.94 17.27,18.2L15.74,16.67C17.78,15.54 19.46,13.9 20.56,12C19.17,9.62 16.34,8 13,8C12.13,8 11.29,8.11 10.47,8.31L8.79,6.63C9.8,6.15 10.87,5.9 12,5.9"/></svg>');
    }
    return this._svg('<svg class="btn-icon" viewBox="0 0 24 24" style="width:16px;height:16px;"><path d="M12,9A3,3 0 0,0 9,12A3,3 0 0,0 12,15A3,3 0 0,0 15,12A3,3 0 0,0 12,9M12,4.5C7,4.5 2.73,7.61 1,12C2.73,16.39 7,19.5 12,19.5C17,19.5 21.27,16.39 23,12C21.27,7.61 17,4.5 12,4.5M12,17A5,5 0 0,1 7,12A5,5 0 0,1 12,7A5,5 0 0,1 17,12A5,5 0 0,1 12,17Z"/></svg>');
  }

  _togglePasswordVisibility(e) {
    e.stopPropagation();
    this._showPassword = !this._showPassword;
    this._elements.eyeIconContainer.replaceChildren(this._getEyeIcon());
    this._updatePasswordNode();
  }

  _updatePasswordNode() {
    const password = this._sipPasswordText || '••••••••';
    this._elements.sipPassword.nodeValue = this._showPassword ? password : '••••••••';
  }

  _copyValue(val) {
    if (!val || val === '-' || val.includes('••')) return;
    navigator.clipboard.writeText(val).then(() => {
      this._elements.toast.classList.add('show');
      setTimeout(() => this._elements.toast.classList.remove('show'), 2000);
    });
  }

  _toggleDrawer() {
    this._drawerOpen = !this._drawerOpen;
    if (this._drawerOpen) {
      this._elements.drawerToggle.classList.add('open');
      this._elements.drawerContent.classList.add('open');
    } else {
      this._elements.drawerToggle.classList.remove('open');
      this._elements.drawerContent.classList.remove('open');
    }
  }

  _updateCard(stateObj) {
    // 1. Online / Offline status
    const isOffline = stateObj.state === 'unavailable' || stateObj.state === 'unknown';
    if (isOffline) {
      this._elements.statusDot.className = 'status-dot offline';
      this._elements.statusText.nodeValue = 'Offline';
      this._elements.liveTitle.nodeValue = 'Stream offline';
    } else {
      this._elements.statusDot.className = 'status-dot';
      this._elements.statusText.nodeValue = 'Connected';
      this._elements.liveTitle.nodeValue = stateObj.attributes.friendly_name || 'TJA470 Intercom';
    }

    // 2. Stream URL proxy & token
    const token = stateObj.attributes.access_token;
    const entityId = stateObj.entity_id;
    if (token && (this._currentToken !== token || this._currentEntityId !== entityId)) {
      this._currentToken = token;
      this._currentEntityId = entityId;
      this._elements.loader.classList.remove('hidden');
      this._elements.img.setAttribute('src', `/api/camera_proxy_stream/${entityId}?token=${token}`);
    }

    // 3. Main unlock door permission/state
    const isUnlockAllowed = stateObj.attributes.door_release_allowed !== false && !isOffline;
    if (isUnlockAllowed) {
      this._elements.unlockBtn.classList.remove('disabled');
    } else {
      this._elements.unlockBtn.classList.add('disabled');
    }

    // 4. Update Technical Details Drawer info
    const attr = stateObj.attributes;
    this._elements.sipUsername.nodeValue = attr.sip_username || '-';
    this._sipPasswordText = attr.sip_password || '';
    this._updatePasswordNode();
    
    this._elements.sipRegistrar.nodeValue = attr.local_ip_address || '-';
    this._elements.stunServer.nodeValue = attr.stun_server || '-';
    this._elements.webrtcPort.nodeValue = attr.remote_sip_ws_port || attr.remote_sip_port || '-';

    // 5. Build extra door rows if configured
    this._updateExtraDoors();
  }

  _updateExtraDoors() {
    const extraDoorsContainer = this._elements.extraDoors;
    const configuredDoors = this._config.door_buttons || [];

    // Clear old elements if list length differs or layout needs refresh
    extraDoorsContainer.replaceChildren();

    configuredDoors.forEach(door => {
      const entityId = door.entity;
      const doorName = door.name || entityId.split('.').pop().replace(/_/g, ' ');

      const doorStateObj = this._hass.states[entityId];
      const isConfirming = this._confirmUnlockMini[entityId] === true;

      const miniBtn = this._el('button', {
        class: `btn-mini-unlock${isConfirming ? ' confirm' : ''}`,
        onclick: () => this._handleMiniUnlock(entityId, doorName)
      }, [
        isConfirming ? 'Sure?' : 'Unlock'
      ]);

      const row = this._el('div', { class: 'extra-door-row' }, [
        this._el('span', { class: 'extra-door-name' }, [doorName]),
        miniBtn
      ]);

      extraDoorsContainer.appendChild(row);
    });
  }

  _handleUnlock() {
    const entityId = this._resolvedEntityId || this._config.entity;
    const stateObj = this._hass.states[entityId];
    const isUnlockAllowed = stateObj && stateObj.attributes.door_release_allowed !== false;
    
    if (!isUnlockAllowed) return;

    if (!this._confirmUnlock) {
      // Step 1: Request confirmation
      this._confirmUnlock = true;
      this._elements.unlockBtn.classList.add('confirm');
      this._elements.unlockBtnText.nodeValue = 'Sure? Click again';
      this._elements.unlockBtnIconContainer.replaceChildren(
        this._svg('<svg class="btn-icon" viewBox="0 0 24 24"><path d="M18 8H17V6C17 3.24 14.76 1 12 1S7 3.24 7 6V8H6C4.9 8 4 8.9 4 10V20C4 21.1 4.9 22 6 22H18C19.1 22 20 21.1 20 20V10C20 8.9 19.1 8 18 8M9 6C9 4.34 10.34 3 12 3S15 4.34 15 6V8H9V6M18 20H6V10H18V20M12 13C10.9 13 10 13.9 10 15S10.9 17 12 17 14 16.1 14 15 13.1 13 12 13Z"/></svg>')
      );

      this._confirmTimeout = setTimeout(() => {
        this._resetUnlockState();
      }, 3000);
    } else {
      // Step 2: Trigger opening
      clearTimeout(this._confirmTimeout);
      this._confirmUnlock = false;

      // Infer active door unlock button
      const openActiveDoorBtn = this._config.open_door_button || 
        entityId.replace(/_camera$/, '_open_active_door').replace(/^camera\./, 'button.');

      this._elements.unlockBtnText.nodeValue = 'Unlocking...';
      this._hass.callService('button', 'press', { entity_id: openActiveDoorBtn })
        .then(() => {
          this._elements.unlockBtnText.nodeValue = 'Door Unlocked';
          setTimeout(() => {
            this._resetUnlockState();
          }, 2000);
        })
        .catch(err => {
          this._elements.unlockBtnText.nodeValue = 'Error!';
          setTimeout(() => {
            this._resetUnlockState();
          }, 2000);
        });
    }
  }

  _resetUnlockState() {
    this._confirmUnlock = false;
    this._elements.unlockBtn.classList.remove('confirm');
    this._elements.unlockBtnText.nodeValue = 'Unlock Door';
    this._elements.unlockBtnIconContainer.replaceChildren(
      this._svg('<svg class="btn-icon" viewBox="0 0 24 24"><path d="M12,17A2,2 0 0,0 14,15C14,13.89 13.11,13 12,13A2,2 0 0,0 10,15A2,2 0 0,0 12,17M18,8A2,2 0 0,1 20,10V20A2,2 0 0,1 18,22H6A2,2 0 0,1 4,20V10C4,8.89 4.9,8 6,8H7V6A5,5 0 0,1 12,1A5,5 0 0,1 17,6V8H18M12,3A3,3 0 0,0 9,6V8H15V6A3,3 0 0,0 12,3Z"/></svg>')
    );
  }

  _handleMiniUnlock(entityId, doorName) {
    if (!this._confirmUnlockMini[entityId]) {
      this._confirmUnlockMini[entityId] = true;
      this._updateExtraDoors();

      this._confirmTimeoutMini[entityId] = setTimeout(() => {
        this._confirmUnlockMini[entityId] = false;
        this._updateExtraDoors();
      }, 3000);
    } else {
      clearTimeout(this._confirmTimeoutMini[entityId]);
      this._confirmUnlockMini[entityId] = false;

      this._hass.callService('button', 'press', { entity_id: entityId })
        .then(() => {
          this._updateExtraDoors();
        })
        .catch(err => {
          this._updateExtraDoors();
        });
    }
  }

  _handleSwitch() {
    const entityId = this._resolvedEntityId || this._config.entity;
    const switchBtn = this._config.switch_camera_button || 
      entityId.replace(/_camera$/, '_switch_camera').replace(/^camera\./, 'button.');

    this._elements.loader.classList.remove('hidden');
    this._hass.callService('button', 'press', { entity_id: switchBtn });
  }
}

customElements.define('tja470-intercom-card', TJA470IntercomCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'tja470-intercom-card',
  name: 'TJA470 Intercom Card',
  description: 'A premium glassmorphic control card for the Hager TJA470 Intercom, showing camera stream and providing door/switcher controls.',
  preview: true
});
