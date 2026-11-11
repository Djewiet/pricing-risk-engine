"""Exception hierarchy of the pricing library.

Every error raised on purpose by the library derives from :class:`PricerError`, so a caller
(for instance the risk service) can isolate library failures from programming errors.
"""


class PricerError(Exception):
    """Base class for all errors raised by the pricing library."""


class MarketDataError(PricerError, ValueError):
    """Market data is inconsistent or invalid (negative spot, unsorted pillars, ...)."""


class MissingMarketDataError(PricerError, KeyError):
    """A pricing call requested market data that the snapshot does not contain."""


class BootstrapError(PricerError, RuntimeError):
    """A curve bootstrap could not reprice one of its input instruments."""
