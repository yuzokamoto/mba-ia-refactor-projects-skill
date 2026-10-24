def configure_connection(app, lifecycle):
    """Registra somente o gancho de encerramento do contexto Flask."""
    app.teardown_appcontext(lifecycle.release)
