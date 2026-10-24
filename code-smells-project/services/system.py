from constants import API_VERSION


class SystemService:
    def __init__(self, system):
        self.system = system

    def health(self):
        return {"status": "ok", "database": "connected", "counts": self.system.counts(),
                "versao": API_VERSION, "ambiente": "producao"}

    def reset(self):
        self.system.reset()
