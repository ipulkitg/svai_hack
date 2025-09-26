import daft
from daft.functions import embed_image

ROW_LIMIT = 1000

URLs = [ 
    "https://www.youtube.com/watch?v=WAsmZJ2kff0", 
    "https://www.youtube.com/watch?v=BLcKDQRTFKY", 
    "https://www.youtube.com/watch?v=Qnw6059ddgE", 
    "https://www.youtube.com/watch?v=eYXDSuNpKTk", 
    "https://www.youtube.com/watch?v=3JWrg1DitaA", 
]

df_frames = daft.read_video_frames(
    URLs,
    image_height=288,
    image_width=288,
).limit(ROW_LIMIT).collect() # Eagerly collect to prevent re-downloading from yt

df_emb = df_frames.with_column(
    "image_embeddings", 
    embed_image(
        df_frames["data"], 
        model_name="google/siglip2-base-patch16-512", 
        provider="transformers",
    )
)
