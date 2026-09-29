"""Email signup form (LeadConnector embed) shared by the homepage and sign pages."""

SIGNUP_HEADINGS = {
    "en": "Get the weekly digest in your inbox",
    "es": "Recibe el resumen semanal en tu correo",
}

SIGNUP_BLURBS = {
    "en": "Free. Let the digest come to you. Choose your sign, and we’ll send it to your inbox each week.",
    "es": "Gratis. Deja que el resumen llegue a ti. Elige tu signo y te lo enviaremos cada semana.",
}

FORM_EMBED = """<iframe
        src="https://api.leadconnectorhq.com/widget/form/DOi6JikWpGIuE9OdCUye"
        style="width:100%;height:100%;border:none;border-radius:8px"
        id="inline-DOi6JikWpGIuE9OdCUye"
        data-layout="{'id':'INLINE'}"
        data-trigger-type="alwaysShow"
        data-trigger-value=""
        data-activation-type="alwaysActivated"
        data-activation-value=""
        data-deactivation-type="neverDeactivate"
        data-deactivation-value=""
        data-form-name="Weekly Tarot Digest – Email Signup"
        data-height="434"
        data-layout-iframe-id="inline-DOi6JikWpGIuE9OdCUye"
        data-form-id="DOi6JikWpGIuE9OdCUye"
        data-cookie-consent="true"
        data-cookie-consent-provider="auto"
        title="Weekly Tarot Digest – Email Signup">
      </iframe>
      <script src="https://link.msgsndr.com/js/form_embed.js"></script>"""


def render_signup_section(lang: str) -> str:
    return f"""<section class="signup-section">
      <h2>{SIGNUP_HEADINGS[lang]}</h2>
      <p class="signup-blurb">{SIGNUP_BLURBS[lang]}</p>
      <div class="signup-form">
      {FORM_EMBED}
      </div>
    </section>"""
