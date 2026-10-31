"""Channel error types."""


class ChannelClosed(Exception):
    """Raised when operating on a closed channel."""


class ChannelFull(Exception):
    """Raised by try_send() when a bounded channel is full."""


class ChannelEmpty(Exception):
    """Raised by try_recv() when the channel is empty."""
