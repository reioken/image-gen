# Product brief (example)

Product: a 50 ml amber glass perfume bottle with a matte black cap and a
minimalist white label reading "AURA".

Brand: premium, understated, modern.

Campaign: launch hero imagery for e-commerce and social. Clean, editorial,
high-end.

Audience: design-conscious 25–45.

No-gos: do not change the bottle shape, the cap, the label text or the logo;
no extra bottles; no warped or melted geometry; no watermarks.

Use this brief with:

    python -m product_image_batch \
      --reference ./product.png \
      --brief ./examples/briefing.md --generate-prompts 20 \
      --providers openai --out ./outputs/aura
