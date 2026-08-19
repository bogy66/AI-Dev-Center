import requests
import time

from app.logger import get_logger


logger = get_logger("ollama")


class OllamaClient:

    def __init__(
        self,
        url="http://localhost:11434",
        model="llama3.2:3b"
    ):
        self.url = url
        self.model = model


    def generate(
        self,
        prompt,
        max_tokens=400
    ):

        start = time.time()

        logger.info(
            f"START model={self.model} prompt={len(prompt)} chars"
        )


        response = requests.post(
            f"{self.url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,

                "options": {
                    "num_predict": max_tokens,
                    "temperature": 0.2
                }
            },
            timeout=300
        )


        duration = time.time() - start


        response.raise_for_status()

        data = response.json()


        logger.info(
            f"DONE {duration:.2f}s "
            f"response_chars={len(data.get('response',''))} "
            f"tokens={data.get('eval_count','?')}"
        )


        return data.get(
            "response",
            ""
        )
