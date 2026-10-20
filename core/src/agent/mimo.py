from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from openai import OpenAIError

DEADLINE_SECONDS = 180


class MimoTimeout(OpenAIError):
    pass


def chat(client, deadline: float = DEADLINE_SECONDS, **request):
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(client.chat.completions.create, **request)
    try:
        return future.result(timeout=deadline)
    except FutureTimeout as error:
        client.close()
        raise MimoTimeout(f"MiMo sent no complete answer within {deadline:.0f} s.") from error
    finally:
        pool.shutdown(wait=False)
