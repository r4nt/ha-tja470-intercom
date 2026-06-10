if (!customElements.get('tja470-intercom-card')) {
  import('/tja470-intercom/tja470-intercom-card.js?v=1.0.9');
}

class TJA470IntercomPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          height: 100%;
          width: 100%;
          overflow: auto;
          box-sizing: border-box;
          background-color: var(--primary-background-color, #111111);
          padding: 16px;
        }
        .container {
          max-width: 600px;
          margin: 0 auto;
          display: flex;
          flex-direction: column;
          justify-content: center;
          min-height: calc(100vh - 64px - 32px);
        }
      </style>
      <div class="container" id="container">
        <div id="status" style="color: #888; text-align: center; font-family: sans-serif;">
          Loading intercom card...
        </div>
      </div>
    `;
    this._hass = null;
    this._card = null;

    // Wait until the custom element is defined, then build it
    customElements.whenDefined('tja470-intercom-card').then(() => {
      const statusEl = this.shadowRoot.getElementById('status');

      if (!this._card) {
        this._card = document.createElement('tja470-intercom-card');
        this._card.setConfig({});
        this.shadowRoot.getElementById('container').appendChild(this._card);
        if (this._hass) {
          this._card.hass = this._hass;
        }
        if (statusEl) {
          statusEl.style.display = 'none'; // hide the loading status once card is ready
        }
      }
    }).catch(err => {
      const statusEl = this.shadowRoot.getElementById('status');
      if (statusEl) {
        statusEl.innerText = 'Failed to load card: ' + err;
        statusEl.style.color = 'red';
      }
    });
  }

  set hass(hass) {
    this._hass = hass;
    if (this._card) {
      this._card.hass = hass;
    }
  }
}

customElements.define('tja470-intercom-panel', TJA470IntercomPanel);
