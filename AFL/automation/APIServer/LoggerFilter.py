class LoggerFilter(object):
    def __init__(self, *filters):
        from werkzeug import serving

        self.filters = filters
        self._log_request = serving.WSGIRequestHandler.log_request

        parent = self

        def log_request(self, *args, **kwargs):
            if any(filter in self.requestline for filter in parent.filters):
                return

            parent._log_request(self, *args, **kwargs)

        serving.WSGIRequestHandler.log_request = log_request
