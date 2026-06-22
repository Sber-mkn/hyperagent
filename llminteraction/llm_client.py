import requests
import json
from typing import List, Dict, Any, Optional
import time


OLLAMA_URL = "http://localhost:11434/api/chat"


class LLMClient:

    def __init__(self, url: str, model: str, **kwargs: int | float | str | bool):
        self.__url: str = url
        self.model: str = model
        self.options: Dict[str, int | float | str | bool] | None = kwargs
        self.start_time: float = time.time()
        self.is_active: bool = False


    @property
    def time_alive(self) -> float | None:
        return time.time() - self.start_time if self.is_active else None


    def send(
            self,
            messages: List[Dict[str, Any]],
            tools: Optional[List[Dict[str, Any]]] = None,
            think: bool = False,
            timeout: int = 120
    ) -> Dict[str, Any]:

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False
        }

        if tools:
            payload["tools"] = tools
        if self.options:
            payload["options"] = self.options

        response = requests.post(
            self.__url,
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                "think": think
            },
            timeout=timeout
        )

        # try:
        response.raise_for_status()
        return response.json()

        # except requests.exceptions.ConnectionError:
        #     print("Ollama не запущена или недоступна на localhost:11434. Запустите `ollama serve`.")
        #
        # except requests.exceptions.HTTPError as e:
        #     print(f"Ollama вернула ошибку: {e.response.status_code} — {e.response.text}")
        #
        # except requests.exceptions.Timeout:
        #     print("Модель не ответила за отведённое время (timeout). Увеличьте timeout или проверьте, что модель грузится.")


    def load(self, model: str, keep_alive: str, timeout: int = 120) -> bool:
        """Загрузка модели в память на `keep_alive` времени"""
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": "",
                "keep_alive": keep_alive
            },
            timeout=timeout
        )




    def unload_model(self, model: str, timeout: int = 120) -> None:
        """Выгрузка модели из памяти"""
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": "",
                "keep_alive": 0
            },
            timeout=timeout
        )






llm_gemma = LLMClient(OLLAMA_URL, "gemma4:12b-64k", temperature=0.2, thinking=False)

print(llm_gemma.send(
    [
        {
            "role": "system",
            "content": "Пиши каждое слово на отдельной строке."
        },
        {
            "role": "user",
            "content": "Напиши два-три предложения про Александра Сергеевича Пушкина."
        }
    ]
))