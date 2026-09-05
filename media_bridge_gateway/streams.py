"""시작 전 취소를 포함한 응답 스트림 자원 소유권."""
from collections.abc import AsyncIterator, Awaitable, Callable

from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send


class ResourceStream:
    def __init__(self, source: AsyncIterator[bytes], close: Callable[[], Awaitable[None]]) -> None:
        self._source = source
        self._close = close
        self._closed = False

    def __aiter__(self) -> "ResourceStream":
        return self

    async def __anext__(self) -> bytes:
        if self._closed:
            raise StopAsyncIteration
        try:
            return await anext(self._source)
        except BaseException:
            await self.aclose()
            raise

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            close = getattr(self._source, "aclose", None)
            if callable(close):
                await close()
        finally:
            await self._close()


class ClosingStreamingResponse(StreamingResponse):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            close = getattr(self.body_iterator, "aclose", None)
            if callable(close):
                await close()
