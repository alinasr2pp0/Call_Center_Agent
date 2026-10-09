"""The Agent: everything that decides and says something to the customer.

service.py   answer / clarify / escalate decision        prompts.py   fixed replies + LLM prompts
llm.py       OpenRouter chat + Tavily web search         speech.py    Groq speech-to-text / text-to-speech
tickets.py   ticket workflow                             followup.py  Vonage follow-up calls
errors.py    errors shared by the providers

Knowledge retrieval is not here: the Agent asks the ``app.rag`` package.
"""
