import os
from writerai import Writer
import dotenv

dotenv.load_env()


client = Writer(
    # This is the default and can be omitted
    api_key=os.environ.get("WRITER_API_KEY"),
)

application_generate_content_response = client.applications.generate_content(
    application_id="f70c88ec-1fe4-4b2e-a6fc-53f413d4ed75",
    inputs=[
        {"id": "Copy", "value": [""]},
        {"id": "Purpose of copy", "value": [""]},
        {"id": "Language", "value": [""]},
    ],
)

print(application_generate_content_response)
