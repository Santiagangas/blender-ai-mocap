class EngineError(Exception):
    """Error with a stable machine-readable code reported to the add-on."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message
