class WCLError(Exception):
    """Base class for safe, caller-facing Warcraft Logs integration failures."""


class InvalidReportReference(WCLError, ValueError): pass
class AuthenticationError(WCLError): pass
class ReportUnavailable(WCLError): pass
class MalformedResponse(WCLError): pass
class RateLimitError(WCLError): pass
class PaginationError(WCLError): pass
class TransportError(WCLError): pass
class SnapshotError(WCLError, ValueError): pass
