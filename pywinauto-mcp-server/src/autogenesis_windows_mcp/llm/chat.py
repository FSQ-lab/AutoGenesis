# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from autogenesis_agent_contract import SecretRef, SecretReferenceError, resolve
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage
from ..llm.prompt import img_task_prompt, ImgTaskResponse
import os
import base64
import io
from PIL import Image
import requests
import logging
from pathlib import Path
from dotenv import load_dotenv

DEFAULT_TEMPERATURE = 0.2
DEFAULT_MODEL_NAME = "azure gpt-4o 2025-01-01-preview"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_MAX_RETRIES = 2
DEFAULT_TIMEOUT = 60
DEFAULT_LOCAL_LM_ENDPOINT = "http://localhost:11434"

# Environment variable names for configuration
AZURE_OPENAI_API_KEY_ENV = "AZURE_OPENAI_API_KEY"
AZURE_OPENAI_ENDPOINT_ENV = "AZURE_OPENAI_ENDPOINT"


class LLMClient:
    """
    A client for interacting with various LLM providers.

    """

    def __init__(self):
        load_dotenv(Path.cwd() / ".env", override=False)
        self.model_name = DEFAULT_MODEL_NAME
        self.temperature = DEFAULT_TEMPERATURE
        self.max_tokens = DEFAULT_MAX_TOKENS
        self.max_retries = DEFAULT_MAX_RETRIES
        self.timeout = DEFAULT_TIMEOUT
        self.api_key_ref = SecretRef(**{"$secret": f"env:{AZURE_OPENAI_API_KEY_ENV}"})
        self.azure_endpoint = os.getenv(AZURE_OPENAI_ENDPOINT_ENV)
        self.local_lm_endpoint = DEFAULT_LOCAL_LM_ENDPOINT

    def get_azure_model(
        self,
    ) -> AzureChatOpenAI:
        """
        Returns an instance of the appropriate chat model based on the model name.

        Raises:
            ValueError: If the model name is invalid or required environment variables are not set.
        """
        # currently only support Azure OpenAI
        if self.model_name.startswith("azure"):
            items = self.model_name.split()
            if len(items) < 2:
                raise ValueError("Azure model name must be in the format 'azure <deployment_name> <api_version>'")

            try:
                api_key = resolve(self.api_key_ref)
            except SecretReferenceError as error:
                raise ValueError(f"{AZURE_OPENAI_API_KEY_ENV} environment variable is not set") from error
            if not self.azure_endpoint:
                raise ValueError(f"{AZURE_OPENAI_ENDPOINT_ENV} environment variable is not set")

            return AzureChatOpenAI(
                azure_deployment=items[1],
                api_version=items[2],
                azure_endpoint=self.azure_endpoint,
                temperature=self.temperature,
                api_key=api_key,
                max_tokens=self.max_tokens,
                max_retries=self.max_retries,
                timeout=self.timeout,
            )
        else:
            raise ValueError("Unsupported visual verification model.")

    def compress_image(self, image_data: bytes, target_length: int = 60000) -> bytes:
        """
        Compresses an image to a target length in bytes.

        Args:
            image_data (bytes): The original image data.
            target_length (int): The desired length of the compressed image data.

        Returns:
            bytes: Compressed image data.
        """
        image = Image.open(io.BytesIO(image_data))
        if image.mode != "RGB":
            image = image.convert("RGB")

        quality = 50
        min_quality = 30

        while quality >= min_quality:
            compressed_buffer = io.BytesIO()
            image.save(compressed_buffer, format="JPEG", quality=quality)
            compressed_size = compressed_buffer.tell()

            if compressed_size <= target_length:
                return compressed_buffer.getvalue()

            quality -= 10

        # If we reach here, the image is still too large, so we try to compress it further
        compressed_buffer = io.BytesIO()
        image.save(compressed_buffer, format="JPEG", quality=min_quality)
        if compressed_buffer.tell() > target_length:
            # If we reach here, the image is still too large, so we try to compress it further
            scale_factor = 0.5
            new_size = (int(image.width * scale_factor), int(image.height * scale_factor))
            resized_image = image.resize(new_size, Image.Resampling.LANCZOS)
            compressed_buffer = io.BytesIO()
            resized_image.save(compressed_buffer, format="JPEG", quality=min_quality)
            if compressed_buffer.tell() > target_length:
                # If we reach here, the image is still too large, so we try to compress it further
                scale_factor = 0.3
                new_size = (int(image.width * scale_factor), int(image.height * scale_factor))
                resized_image = image.resize(new_size, Image.Resampling.LANCZOS)
                compressed_buffer = io.BytesIO()
                resized_image.save(compressed_buffer, format="JPEG", quality=min_quality)
        if compressed_buffer.tell() > target_length:
            raise Exception(f"Image is still too large after compression: {compressed_buffer.tell()} bytes")

        return compressed_buffer.getvalue()

    def evaluate_task(self, task_info: str, image_data: bytes = None) -> ImgTaskResponse:
        if os.getenv(AZURE_OPENAI_API_KEY_ENV) and self.azure_endpoint:
            return self.evaluate_task_with_azure(task_info, image_data)
        elif self.local_lm_endpoint:
            return self.evaluate_task_with_local_lm(task_info, image_data)
        raise Exception("No valid LLM provider configured.")

    def evaluate_task_with_azure(self, task_info: str, image_data: bytes = None) -> ImgTaskResponse:
        """
        Evaluates whether a given image satisfies the specified task description.

        Args:
            task_info (str): The task description to evaluate.
            image_data (bytes): The image data in binary format (default: None).
            compress (int): Compression quality for the image (default: 50).

        Returns:
            ImgTaskResponse: A structured response containing the evaluation result and reasoning.
        """
        model = self.get_azure_model()
        compressed_bytes = self.compress_image(image_data=image_data)
        image_base64 = base64.b64encode(compressed_bytes).decode("utf-8")
        message = HumanMessage(
            content=[
                {"type": "text", "text": img_task_prompt(task_info)},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                },
            ]
        )
        structured_llm = model.with_structured_output(ImgTaskResponse)
        res = structured_llm.invoke([message])
        return res

    def evaluate_task_with_local_lm(self, task_info: str, image_data: bytes = None) -> ImgTaskResponse:
        compressed_bytes = self.compress_image(image_data=image_data)
        image_base64 = base64.b64encode(compressed_bytes).decode("utf-8")
        prompt = img_task_prompt(task_info)
        output_format = ImgTaskResponse.get_prompt_format()
        payload = {
            "model": "gpt-5.4",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "\n".join([prompt, output_format])},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                    ],
                }
            ],
            "stream": False,
        }
        response = requests.post(f"{self.local_lm_endpoint}/v1/chat/completions", json=payload, timeout=30)
        if response.status_code != 200:
            raise RuntimeError("Local visual verification provider returned an unsuccessful response.")
        data = response.json()
        full_response = ""
        if "choices" in data:
            for choice in data["choices"]:
                if "message" in choice and "content" in choice["message"]:
                    full_response += choice["message"]["content"]

        full_response = full_response.replace("```json", "").replace("```", "")
        res = ImgTaskResponse.model_validate_json(full_response)
        return res

    def local_copilot_available(self) -> bool:
        url_tag = f"{self.local_lm_endpoint}/api/tags"
        try:
            response = requests.get(url_tag, timeout=10)
            if response.status_code == 200:
                data = response.json()
                models = data.get("models", [])
                models = [model["name"] for model in models]
                if "gpt-5.4" in models:
                    return True
                else:
                    logging.warning("gpt-5.4 model not found in local copilot tags.")
                    return False
            else:
                logging.error("Local visual verification provider is unavailable.")
                return False
        except Exception as e:
            logging.error("Local visual verification provider is unavailable.")
            return False

    def azure_gpt_available(self) -> bool:
        return bool(os.getenv(AZURE_OPENAI_API_KEY_ENV) and self.azure_endpoint)


def is_ai_enabled() -> bool:
    """Check if AI functionality is properly configured."""
    client = LLMClient()
    return client.azure_gpt_available() or client.local_copilot_available()
