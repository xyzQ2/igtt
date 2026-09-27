Analyze this social-media post as a content strategist.

Target brand: {brand_name}
Brand voice: {brand_voice}
Industry: {industry}
Target market: {target_market}

Do not copy the content. Extract reusable structure only.

If an image is attached, it is the post's cover image. Use it for the hook,
composition, pose and styling; do not describe people's bodies or identity.

Post data:
{post_json}

Determine:

HOOK — what grabs attention immediately?
HOOK TYPE — curiosity / controversy / relatability / surprise / identity / aspiration / humor / disgust / status
PAYOFF — what does the viewer get for continuing?
EMOTIONAL DRIVER — why does anyone care?
HUMOR MECHANISM — if relevant.
SOCIAL DRIVER — why would someone tag or send this to a friend?
COMMENT DRIVER — why would people respond?
REWATCH DRIVER — does the format encourage looping or replay?
VISUAL STRUCTURE — describe the creative format.
CAPTION ROLE — how does the caption contribute?
AUDIENCE — who feels specifically understood by this?
TIMING — is there a cultural or trend component?
WHY IT OVERPERFORMED — the three strongest explanations.
REUSABLE PATTERN — abstract this into a formula reusable without copying it.
  Example: "Highly recognizable situation + escalating frustration + absurd visual payoff."

Score each 0-100: hook, shareability, originality, relatability, rewatchability,
cultural_relevance. Then give an overall ai_virality_score 0-100.

Respond with ONLY a JSON object, no prose and no markdown fence, in exactly this shape:

{{
  "hook": "", "hook_type": "", "payoff": "", "emotional_driver": "",
  "humor_mechanism": "", "social_driver": "", "comment_driver": "",
  "rewatch_driver": "", "visual_structure": "", "caption_role": "",
  "audience": "", "timing": "",
  "why_it_overperformed": ["", "", ""],
  "reusable_pattern": "",
  "scores": {{"hook": 0, "shareability": 0, "originality": 0,
              "relatability": 0, "rewatchability": 0, "cultural_relevance": 0}},
  "ai_virality_score": 0
}}
