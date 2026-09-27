You are evaluating Instagram accounts as monitoring targets for {brand_name}.
Brand voice: {brand_voice}
Industry: {industry}
Target market: {target_market}

Score each candidate 0-100 on how useful it is to monitor, weighting:
- Audience relevance 30%
- Content overlap 25%
- Humor/style compatibility 20%
- Recent performance 15%
- Originality/inspiration value 10%

An account that posts corporate or educational content in the same industry is NOT
relevant — style compatibility matters as much as topic.

Also assign each a category from: {categories}

Candidates:
{candidates}

Respond with ONLY a JSON array, no prose and no markdown fence:

[{{"username": "", "relevance_score": 0, "category": "", "reason": ""}}]
