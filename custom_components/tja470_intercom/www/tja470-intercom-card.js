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
      img {
        width: 100%;
        max-width: 100%;
        height: auto;
        display: block;
      }
      .hidden {
        display: none !important;
      }
    `;
    this.shadowRoot.appendChild(style);

    const title = this._config.name || stateObj.attributes.friendly_name || 'Intercom';
    const header = document.createElement('h2');
    header.textContent = title;

    const imgEl = document.createElement('img');
    imgEl.alt = 'Camera Feed';
    this._elements.img = imgEl;

    this._elements.statusText = document.createTextNode('Connecting...');
    const statusBar = document.createElement('div');
    statusBar.appendChild(document.createTextNode('Status: '));
    statusBar.appendChild(this._elements.statusText);

    const unlockBtn = document.createElement('button');
    unlockBtn.textContent = 'Unlock Door';
    unlockBtn.onclick = () => this._handleUnlock();
    this._elements.unlockBtn = unlockBtn;

    const switchBtn = document.createElement('button');
    switchBtn.textContent = 'Switch Feed';
    switchBtn.onclick = () => this._handleSwitch();
    this._elements.switchBtn = switchBtn;

    const hangupBtn = document.createElement('button');
    hangupBtn.onclick = () => this._handleHangupCall();
    this._elements.hangupBtn = hangupBtn;

    const answerBtn = document.createElement('button');
    answerBtn.textContent = 'Answer';
    answerBtn.onclick = () => this._handleAnswerCall();
    this._elements.answerBtn = answerBtn;

    const controls = document.createElement('div');
    controls.appendChild(unlockBtn);
    controls.appendChild(switchBtn);
    controls.appendChild(hangupBtn);
    controls.appendChild(answerBtn);

    const extraDoors = document.createElement('div');
    extraDoors.style.marginTop = '8px';
    this._elements.extraDoors = extraDoors;

    const card = document.createElement('ha-card');
    card.appendChild(header);
    card.appendChild(imgEl);
    card.appendChild(statusBar);
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
    if (isOffline) {
      statusText = 'Offline';
    } else {
      if (callState === 'ringing') {
        statusText = `Incoming Call: ${caller}`;
      } else if (callState === 'dialing') {
        statusText = `Calling ${caller}...`;
      } else if (callState === 'answered') {
        statusText = `Call Active: ${caller}`;
      } else {
        statusText = 'Connected';
      }
    }

    if (this._elements.statusText) {
      this._elements.statusText.nodeValue = statusText;
    }

    const token = attr.access_token;
    const entityId = stateObj.entity_id;
    if (token && (this._currentToken !== token || this._currentEntityId !== entityId)) {
      this._currentToken = token;
      this._currentEntityId = entityId;
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
      this._elements.hangupBtn.textContent = 'Decline';
      this._elements.hangupBtn.classList.remove('hidden');
    } else if (callState === 'dialing') {
      this._elements.switchBtn.classList.add('hidden');
      this._elements.unlockBtn.classList.remove('hidden');
      this._elements.answerBtn.classList.add('hidden');
      this._elements.hangupBtn.textContent = 'Cancel';
      this._elements.hangupBtn.classList.remove('hidden');
    } else if (callState === 'answered') {
      this._elements.switchBtn.classList.add('hidden');
      this._elements.unlockBtn.classList.remove('hidden');
      this._elements.answerBtn.classList.add('hidden');
      this._elements.hangupBtn.textContent = 'Hang Up';
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

    extraDoorsContainer.replaceChildren();

    configuredDoors.forEach(door => {
      const entityId = door.entity;
      const doorName = door.name || entityId.split('.').pop().replace(/_/g, ' ');

      const row = document.createElement('div');
      row.style.marginTop = '4px';

      const nameSpan = document.createElement('span');
      nameSpan.textContent = doorName + ': ';
      row.appendChild(nameSpan);

      if (door.sip_id) {
        const callBtn = document.createElement('button');
        callBtn.textContent = 'Call';
        callBtn.onclick = () => this._handleInitiateCallForSip(door.sip_id);
        row.appendChild(callBtn);
        row.appendChild(document.createTextNode(' '));
      }

      const unlockBtn = document.createElement('button');
      unlockBtn.textContent = 'Unlock';
      unlockBtn.onclick = () => this._handleMiniUnlock(entityId);
      row.appendChild(unlockBtn);

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
