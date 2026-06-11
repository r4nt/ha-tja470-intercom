class TJA470IntercomCard extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._config = null;
    this._elements = {};
    this._currentToken = null;
    this._currentEntityId = null;
    this._discoveredDoorButtons = null;
    this._discoveryInProgress = false;
  }

  setConfig(config) {
    if (config.entity && !config.entity.startsWith('camera.')) {
      throw new Error('The entity must be a camera entity.');
    }
    this._config = config;
  }

  set hass(hass) {
    this._hass = hass;
    
    let entityId = this._config && this._config.entity;
    if (!entityId || !hass.states[entityId]) {
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
      this._renderError('Entity not found: ' + entityId);
      return;
    }

    this._resolvedEntityId = entityId;

    if (!this.shadowRoot) {
      this._firstRender(stateObj);
    } else {
      this._updateCard(stateObj);
    }

    if (!this._discoveredDoorButtons && !this._discoveryInProgress && !(this._config && this._config.door_buttons)) {
      this._discoverDoorButtons();
    }
  }

  async _discoverDoorButtons() {
    this._discoveryInProgress = true;
    try {
      const entities = await this._hass.callWS({ type: 'config/entity_registry/list' });
      const tjaEntities = entities.filter(e => e.platform === 'tja470_intercom');

      const cameraReg = tjaEntities.find(e => e.entity_id === this._resolvedEntityId);
      if (!cameraReg) {
        this._discoveredDoorButtons = [];
        this._discoveryInProgress = false;
        return;
      }
      const controllerDeviceId = cameraReg.device_id;

      const doorButtonEntities = tjaEntities.filter(e =>
        e.entity_id.startsWith('button.') &&
        e.device_id &&
        e.device_id !== controllerDeviceId
      );

      if (doorButtonEntities.length === 0) {
        this._discoveredDoorButtons = [];
        this._discoveryInProgress = false;
        this._updateExtraDoors();
        return;
      }

      const devices = await this._hass.callWS({ type: 'config/device_registry/list' });
      const deviceMap = {};
      const deviceSipMap = {};
      for (const dev of devices) {
        deviceMap[dev.id] = dev.name || dev.name_by_user || 'Door Station';
        const tjaIdent = dev.identifiers && dev.identifiers.find(id => id[0] === 'tja470_intercom' && id[1].startsWith('door_'));
        if (tjaIdent) {
          deviceSipMap[dev.id] = tjaIdent[1].replace('door_', '');
        }
      }

      this._discoveredDoorButtons = doorButtonEntities.map(e => ({
        entity: e.entity_id,
        name: deviceMap[e.device_id] || e.entity_id.split('.').pop().replace(/_open$/, '').replace(/_/g, ' '),
        sip_id: deviceSipMap[e.device_id] || null
      }));

      this._discoveryInProgress = false;
      this._updateExtraDoors();
    } catch (err) {
      this._discoveryInProgress = false;
      this._discoveredDoorButtons = [];
    }
  }

  getCardSize() {
    return 5;
  }

  _renderError(message) {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: 'open' });
    }
    const errorCard = document.createElement('ha-card');
    errorCard.textContent = message;
    this.shadowRoot.replaceChildren(errorCard);
  }

  _firstRender(stateObj) {
    this.attachShadow({ mode: 'open' });

    const style = document.createElement('style');
    style.textContent = `
      :host {
        display: block;
      }
      ha-card {
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 12px;
        border-radius: var(--ha-card-border-radius, 12px);
        background: var(--ha-card-background, var(--card-background-color, #fff));
        color: var(--primary-text-color, #212121);
        transition: all 0.3s ease;
        box-shadow: var(--ha-card-box-shadow, 0 2px 2px 0 rgba(0,0,0,0.14), 0 1px 5px 0 rgba(0,0,0,0.12), 0 3px 1px -2px rgba(0,0,0,0.2));
      }
      .header-container {
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
      h2.title {
        margin: 0;
        font-size: 1.25rem;
        font-weight: 500;
        color: var(--primary-text-color);
        letter-spacing: -0.01em;
      }
      .feed-container {
        position: relative;
        width: 100%;
        aspect-ratio: var(--aspect-ratio, 4 / 3);
        border-radius: 8px;
        overflow: hidden;
        background: var(--primary-background-color, #1a1a1a);
        box-shadow: inset 0 0 20px rgba(0, 0, 0, 0.4);
      }
      .feed-container img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        opacity: 0;
        transition: opacity 0.5s ease-in-out;
        display: block;
      }
      .feed-container img.loaded {
        opacity: 1;
      }
      .placeholder {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        color: #fff;
        z-index: 1;
        transition: opacity 0.3s ease;
        background: linear-gradient(135deg, #2a2a2a 0%, #151515 100%);
      }
      .placeholder.hidden {
        display: none !important;
      }
      .placeholder ha-icon {
        --mdc-icon-size: 48px;
        margin-bottom: 12px;
        animation: pulse 2s infinite ease-in-out;
        color: rgba(255, 255, 255, 0.5);
      }
      .placeholder span {
        font-size: 0.95rem;
        font-weight: 500;
        letter-spacing: 0.01em;
        color: rgba(255, 255, 255, 0.7);
      }
      .status-overlay {
        position: absolute;
        bottom: 12px;
        left: 12px;
        background: rgba(0, 0, 0, 0.65);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        color: #fff;
        padding: 5px 12px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 500;
        letter-spacing: 0.02em;
        display: flex;
        align-items: center;
        gap: 6px;
        border: 1px solid rgba(255, 255, 255, 0.15);
        z-index: 2;
      }
      .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background-color: var(--success-color, #4caf50);
        box-shadow: 0 0 8px var(--success-color, #4caf50);
      }
      .status-dot.connecting {
        background-color: var(--warning-color, #ff9800);
        box-shadow: 0 0 8px var(--warning-color, #ff9800);
        animation: blink 1.5s infinite ease-in-out;
      }
      .status-dot.offline {
        background-color: var(--error-color, #f44336);
        box-shadow: 0 0 8px var(--error-color, #f44336);
      }
      .status-dot.ringing {
        background-color: var(--error-color, #f44336);
        box-shadow: 0 0 8px var(--error-color, #f44336);
        animation: blink 0.8s infinite ease-in-out;
      }
      .controls {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(90px, 1fr));
        gap: 8px;
        margin-top: 4px;
      }
      button.btn {
        background: var(--primary-color, #03a9f4);
        color: var(--text-primary-color, #fff);
        border: none;
        padding: 10px 14px;
        border-radius: 8px;
        font-size: 0.9rem;
        font-weight: 500;
        cursor: pointer;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 4px;
        transition: all 0.2s ease;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
      }
      button.btn:hover:not(:disabled) {
        background: var(--accent-color, #ff4081);
        transform: translateY(-1px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.15);
      }
      button.btn:active:not(:disabled) {
        transform: translateY(0);
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
      }
      button.btn:disabled {
        background: var(--disabled-text-color, #bdbdbd);
        color: var(--text-disabled-color, #e0e0e0);
        cursor: not-allowed;
        box-shadow: none;
      }
      button.btn-unlock {
        background: var(--success-color, #4caf50);
      }
      button.btn-unlock:hover:not(:disabled) {
        background: #43a047;
      }
      button.btn-decline {
        background: var(--error-color, #f44336);
      }
      button.btn-decline:hover:not(:disabled) {
        background: #d32f2f;
      }
      button.btn-answer {
        background: var(--success-color, #4caf50);
        animation: pulse-border 1.5s infinite;
      }
      button.btn-answer:hover:not(:disabled) {
        background: #43a047;
      }
      button.btn-switch {
        background: var(--secondary-background-color, #e0e0e0);
        color: var(--primary-text-color, #212121);
      }
      button.btn-switch:hover:not(:disabled) {
        background: var(--divider-color, #bdbdbd);
      }
      button.btn ha-icon {
        --mdc-icon-size: 20px;
      }
      .extra-doors {
        border-top: 1px solid var(--divider-color, #e0e0e0);
        padding-top: 8px;
        margin-top: 4px;
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .extra-doors.hidden {
        display: none !important;
      }
      .extra-door-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: var(--secondary-background-color, #fafafa);
        padding: 6px 12px;
        border-radius: 6px;
        border: 1px solid var(--divider-color, #e0e0e0);
      }
      .extra-door-name {
        font-size: 0.9rem;
        font-weight: 500;
      }
      .extra-door-actions {
        display: flex;
        gap: 6px;
      }
      button.btn-mini {
        padding: 6px 10px;
        font-size: 0.8rem;
        border-radius: 6px;
        gap: 2px;
        flex-direction: row;
      }
      button.btn-mini ha-icon {
        --mdc-icon-size: 14px;
      }
      .hidden {
        display: none !important;
      }
      
      @keyframes pulse {
        0% { transform: scale(1); opacity: 0.6; }
        50% { transform: scale(1.05); opacity: 1; }
        100% { transform: scale(1); opacity: 0.6; }
      }
      @keyframes blink {
        0% { opacity: 0.3; }
        50% { opacity: 1; }
        100% { opacity: 0.3; }
      }
      @keyframes pulse-border {
        0% { box-shadow: 0 0 0 0 rgba(76, 175, 80, 0.4); }
        70% { box-shadow: 0 0 0 10px rgba(76, 175, 80, 0); }
        100% { box-shadow: 0 0 0 0 rgba(76, 175, 80, 0); }
      }
    `;
    this.shadowRoot.appendChild(style);

    const title = this._config.name || stateObj.attributes.friendly_name || 'Intercom';
    
    // Header
    const headerContainer = document.createElement('div');
    headerContainer.className = 'header-container';
    const header = document.createElement('h2');
    header.className = 'title';
    header.textContent = title;
    headerContainer.appendChild(header);

    // Feed Container
    const feedContainer = document.createElement('div');
    feedContainer.className = 'feed-container';
    if (this._config.aspect_ratio) {
      feedContainer.style.setProperty('--aspect-ratio', this._config.aspect_ratio);
    }
    this._elements.feedContainer = feedContainer;

    // Placeholder inside feed
    const placeholder = document.createElement('div');
    placeholder.className = 'placeholder';
    const placeholderIcon = document.createElement('ha-icon');
    placeholderIcon.setAttribute('icon', 'mdi:camera');
    const placeholderText = document.createElement('span');
    placeholderText.textContent = 'Awaiting Camera Stream...';
    placeholder.appendChild(placeholderIcon);
    placeholder.appendChild(placeholderText);
    this._elements.placeholder = placeholder;
    feedContainer.appendChild(placeholder);

    // Image inside feed
    const imgEl = document.createElement('img');
    imgEl.alt = 'Camera Feed';
    imgEl.onload = () => {
      imgEl.classList.add('loaded');
      placeholder.classList.add('hidden');
    };
    this._elements.img = imgEl;
    feedContainer.appendChild(imgEl);

    // Status dot and text overlay inside feed
    const statusOverlay = document.createElement('div');
    statusOverlay.className = 'status-overlay';
    const statusDot = document.createElement('div');
    statusDot.className = 'status-dot';
    statusOverlay.appendChild(statusDot);
    const statusTextSpan = document.createElement('span');
    statusOverlay.appendChild(statusTextSpan);
    this._elements.statusDot = statusDot;
    this._elements.statusTextSpan = statusTextSpan;
    feedContainer.appendChild(statusOverlay);

    // Controls
    const controls = document.createElement('div');
    controls.className = 'controls';

    const unlockBtn = document.createElement('button');
    unlockBtn.className = 'btn btn-unlock';
    const unlockIcon = document.createElement('ha-icon');
    unlockIcon.setAttribute('icon', 'mdi:door-open');
    unlockBtn.appendChild(unlockIcon);
    unlockBtn.appendChild(document.createTextNode('Unlock'));
    unlockBtn.onclick = () => this._handleUnlock();
    this._elements.unlockBtn = unlockBtn;
    controls.appendChild(unlockBtn);

    const switchBtn = document.createElement('button');
    switchBtn.className = 'btn btn-switch';
    const switchIcon = document.createElement('ha-icon');
    switchIcon.setAttribute('icon', 'mdi:camera-switch');
    switchBtn.appendChild(switchIcon);
    switchBtn.appendChild(document.createTextNode('Switch'));
    switchBtn.onclick = () => this._handleSwitch();
    this._elements.switchBtn = switchBtn;
    controls.appendChild(switchBtn);

    const hangupBtn = document.createElement('button');
    hangupBtn.className = 'btn btn-decline';
    const hangupIcon = document.createElement('ha-icon');
    hangupIcon.setAttribute('icon', 'mdi:phone-hangup');
    const hangupSpan = document.createElement('span');
    hangupSpan.textContent = 'Decline';
    hangupBtn.appendChild(hangupIcon);
    hangupBtn.appendChild(hangupSpan);
    hangupBtn.onclick = () => this._handleHangupCall();
    this._elements.hangupBtn = hangupBtn;
    this._elements.hangupSpan = hangupSpan;
    this._elements.hangupIcon = hangupIcon;
    controls.appendChild(hangupBtn);

    const answerBtn = document.createElement('button');
    answerBtn.className = 'btn btn-answer';
    const answerIcon = document.createElement('ha-icon');
    answerIcon.setAttribute('icon', 'mdi:phone');
    answerBtn.appendChild(answerIcon);
    answerBtn.appendChild(document.createTextNode('Answer'));
    answerBtn.onclick = () => this._handleAnswerCall();
    this._elements.answerBtn = answerBtn;
    controls.appendChild(answerBtn);

    const extraDoors = document.createElement('div');
    extraDoors.className = 'extra-doors hidden';
    this._elements.extraDoors = extraDoors;

    const card = document.createElement('ha-card');
    card.appendChild(headerContainer);
    card.appendChild(feedContainer);
    card.appendChild(controls);
    card.appendChild(extraDoors);

    this.shadowRoot.appendChild(card);
    this._updateCard(stateObj);
  }

  _updateCard(stateObj) {
    const isOffline = stateObj.state === 'unavailable' || stateObj.state === 'unknown';
    const attr = stateObj.attributes || {};
    const callState = attr.call_state || 'idle';
    const caller = attr.caller || 'Unknown Caller';

    let statusText = 'Connecting...';
    let statusClass = 'connecting';
    if (isOffline) {
      statusText = 'Offline';
      statusClass = 'offline';
    } else {
      if (callState === 'ringing') {
        statusText = `Call from: ${caller}`;
        statusClass = 'ringing';
      } else if (callState === 'dialing') {
        statusText = `Calling ${caller}...`;
        statusClass = 'connecting';
      } else if (callState === 'answered') {
        statusText = `Call Active: ${caller}`;
        statusClass = 'ringing';
      } else {
        statusText = 'Connected';
        statusClass = 'connected';
      }
    }

    if (this._elements.statusTextSpan) {
      this._elements.statusTextSpan.textContent = statusText;
    }
    if (this._elements.statusDot) {
      this._elements.statusDot.className = `status-dot ${statusClass}`;
    }

    const token = attr.access_token;
    const entityId = stateObj.entity_id;
    if (token && (this._currentToken !== token || this._currentEntityId !== entityId)) {
      this._currentToken = token;
      this._currentEntityId = entityId;
      this._elements.img.classList.remove('loaded');
      this._elements.placeholder.classList.remove('hidden');
      this._elements.img.src = `/api/camera_proxy_stream/${entityId}?token=${token}`;
    }

    if (this._elements.unlockBtn) {
      this._elements.unlockBtn.disabled = attr.door_release_allowed === false || isOffline;
    }

    if (callState === 'answered') {
      const isSecure = window.isSecureContext === true || window.location.protocol === 'https:' || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
      if (!this._audioStreaming && isSecure) {
        this._startCallAudio(attr.config_entry_id);
      }
    } else {
      if (this._audioStreaming) {
        this._stopCallAudio();
      }
    }

    if (callState === 'ringing') {
      this._elements.switchBtn.classList.add('hidden');
      this._elements.unlockBtn.classList.add('hidden');
      this._elements.answerBtn.classList.remove('hidden');
      this._elements.hangupSpan.textContent = 'Decline';
      this._elements.hangupIcon.setAttribute('icon', 'mdi:phone-hangup');
      this._elements.hangupBtn.classList.remove('hidden');
    } else if (callState === 'dialing') {
      this._elements.switchBtn.classList.add('hidden');
      this._elements.unlockBtn.classList.remove('hidden');
      this._elements.answerBtn.classList.add('hidden');
      this._elements.hangupSpan.textContent = 'Cancel';
      this._elements.hangupIcon.setAttribute('icon', 'mdi:phone-hangup');
      this._elements.hangupBtn.classList.remove('hidden');
    } else if (callState === 'answered') {
      this._elements.switchBtn.classList.add('hidden');
      this._elements.unlockBtn.classList.remove('hidden');
      this._elements.answerBtn.classList.add('hidden');
      this._elements.hangupSpan.textContent = 'Hang Up';
      this._elements.hangupIcon.setAttribute('icon', 'mdi:phone-hangup');
      this._elements.hangupBtn.classList.remove('hidden');
    } else {
      this._elements.switchBtn.classList.remove('hidden');
      this._elements.unlockBtn.classList.remove('hidden');
      this._elements.answerBtn.classList.add('hidden');
      this._elements.hangupBtn.classList.add('hidden');
    }

    this._updateExtraDoors();
  }

  _updateExtraDoors() {
    const extraDoorsContainer = this._elements.extraDoors;
    if (!extraDoorsContainer) return;
    const configuredDoors = (this._config && this._config.door_buttons) || this._discoveredDoorButtons || [];

    if (configuredDoors.length === 0) {
      extraDoorsContainer.classList.add('hidden');
      return;
    }

    extraDoorsContainer.classList.remove('hidden');
    extraDoorsContainer.replaceChildren();

    configuredDoors.forEach(door => {
      const entityId = door.entity;
      const doorName = door.name || entityId.split('.').pop().replace(/_/g, ' ');

      const row = document.createElement('div');
      row.className = 'extra-door-row';

      const nameSpan = document.createElement('span');
      nameSpan.className = 'extra-door-name';
      nameSpan.textContent = doorName;
      row.appendChild(nameSpan);

      const actionsDiv = document.createElement('div');
      actionsDiv.className = 'extra-door-actions';

      if (door.sip_id) {
        const callBtn = document.createElement('button');
        callBtn.className = 'btn btn-switch btn-mini';
        const callIcon = document.createElement('ha-icon');
        callIcon.setAttribute('icon', 'mdi:phone');
        callBtn.appendChild(callIcon);
        callBtn.appendChild(document.createTextNode('Call'));
        callBtn.onclick = () => this._handleInitiateCallForSip(door.sip_id);
        actionsDiv.appendChild(callBtn);
      }

      const unlockBtn = document.createElement('button');
      unlockBtn.className = 'btn btn-unlock btn-mini';
      const unlockIcon = document.createElement('ha-icon');
      unlockIcon.setAttribute('icon', 'mdi:door-open');
      unlockBtn.appendChild(unlockIcon);
      unlockBtn.appendChild(document.createTextNode('Unlock'));
      unlockBtn.onclick = () => this._handleMiniUnlock(entityId);
      actionsDiv.appendChild(unlockBtn);

      row.appendChild(actionsDiv);
      extraDoorsContainer.appendChild(row);
    });
  }

  _handleUnlock() {
    const entityId = this._resolvedEntityId || this._config.entity;
    const openActiveDoorBtn = this._config.open_door_button || 
      entityId.replace(/_camera$/, '_open_active_door').replace(/^camera\./, 'button.');
    this._hass.callService('button', 'press', { entity_id: openActiveDoorBtn });
  }

  _handleMiniUnlock(entityId) {
    this._hass.callService('button', 'press', { entity_id: entityId });
  }

  _handleAnswerCall() {
    const entityId = this._resolvedEntityId || this._config.entity;
    this._hass.callService('tja470_intercom', 'answer_call', { entity_id: entityId });
  }

  _handleHangupCall() {
    const entityId = this._resolvedEntityId || this._config.entity;
    this._hass.callService('tja470_intercom', 'hangup_call', { entity_id: entityId });
  }

  _handleInitiateCallForSip(sipId) {
    const entityId = this._resolvedEntityId || this._config.entity;
    this._hass.callService('tja470_intercom', 'initiate_call', {
      entity_id: entityId,
      number: sipId
    });
  }

  async _startCallAudio(entryId) {
    if (this._audioStreaming) return;
    this._audioStreaming = true;

    try {
      this._audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 8000 });
      this._nextPlayTime = 0;

      // Acquire microphone stream asynchronously so it doesn't block the WebSocket initialization
      if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
          if (!this._audioStreaming) {
            stream.getTracks().forEach(track => track.stop());
            return;
          }
          this._micStream = stream;
          this._micSource = this._audioCtx.createMediaStreamSource(this._micStream);
          
          this._micProcessor = this._audioCtx.createScriptProcessor(2048, 1, 1);
          this._micProcessor.onaudioprocess = (e) => {
            if (!this._ws || this._ws.readyState !== WebSocket.OPEN) return;
            const inputData = e.inputBuffer.getChannelData(0);
            
            const pcmData = new Int16Array(inputData.length);
            for (let i = 0; i < inputData.length; i++) {
              const s = Math.max(-1, Math.min(1, inputData[i]));
              pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }
            this._ws.send(pcmData.buffer);
          };
          
          this._micSource.connect(this._micProcessor);
          this._micProcessor.connect(this._audioCtx.destination);
        }).catch((micErr) => {
          console.warn("Intercom microphone acquisition failed (listen-only mode):", micErr);
        });
      }

      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const token = this._hass.auth.data.access_token;
      const wsUrl = `${proto}//${window.location.host}/api/tja470_intercom/audio_stream?entry_id=${entryId}&token=${token}`;
      
      this._ws = new WebSocket(wsUrl);
      this._ws.binaryType = 'arraybuffer';
      
      this._ws.onmessage = async (event) => {
        if (!this._audioCtx || this._audioCtx.state === 'suspended') return;
        const arrayBuffer = event.data;
        const int16Array = new Int16Array(arrayBuffer);
        
        const float32Array = new Float32Array(int16Array.length);
        for (let i = 0; i < int16Array.length; i++) {
          float32Array[i] = int16Array[i] / 32768.0;
        }
        
        const buffer = this._audioCtx.createBuffer(1, float32Array.length, 8000);
        buffer.copyToChannel(float32Array, 0);
        
        const source = this._audioCtx.createBufferSource();
        source.buffer = buffer;
        source.connect(this._audioCtx.destination);
        
        const now = this._audioCtx.currentTime;
        if (this._nextPlayTime < now) {
          this._nextPlayTime = now;
        }
        source.start(this._nextPlayTime);
        this._nextPlayTime += buffer.duration;
      };

      this._ws.onclose = () => this._stopCallAudio();
      this._ws.onerror = () => this._stopCallAudio();

    } catch (err) {
      console.error("Failed to start intercom audio streaming:", err);
      if (this._elements.statusText) {
        this._elements.statusText.nodeValue = `Audio Error: ${err.message || err}`;
      }
      this._stopCallAudio();
    }
  }

  _stopCallAudio() {
    this._audioStreaming = false;

    if (this._micProcessor) {
      try { this._micProcessor.disconnect(); } catch(e){}
      this._micProcessor = null;
    }
    if (this._micSource) {
      try { this._micSource.disconnect(); } catch(e){}
      this._micSource = null;
    }
    if (this._micStream) {
      this._micStream.getTracks().forEach(track => track.stop());
      this._micStream = null;
    }
    if (this._audioCtx) {
      try { this._audioCtx.close(); } catch(e){}
      this._audioCtx = null;
    }
    if (this._ws) {
      try { this._ws.close(); } catch(e){}
      this._ws = null;
    }
  }

  _handleSwitch() {
    const entityId = this._resolvedEntityId || this._config.entity;
    const switchBtn = this._config.switch_camera_button || 
      entityId.replace(/_camera$/, '_switch_camera').replace(/^camera\./, 'button.');
    this._currentToken = null;
    this._hass.callService('button', 'press', { entity_id: switchBtn });
  }
}

customElements.define('tja470-intercom-card', TJA470IntercomCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'tja470-intercom-card',
  name: 'TJA470 Intercom Card',
  description: 'A minimal control card for the Hager TJA470 Intercom, showing camera stream and providing door/switcher controls.',
  preview: true
});
