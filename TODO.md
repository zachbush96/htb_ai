1. Remove past targets from the project completely include from GitHub , and when the app starts, remove past projects too.

2. Create an easier way to launch this from a PwnBox , or disposable linux VM

3. Why does the app.py wihtin the home//root directory seem like a markdown file and not an actual python script? Update the files accordingly.

4. The app.py (backend/htbmc/app.py) within the backend directory is HUGE and hard to understand completely. Break it up into more digestable and modular components.

5. Sometimes it seem's like the local ollama-based LLM will not return next-steps. This becomes an issue when we are constantly reaching out to the LLM for next instructions, burning tokens, and not getting a response. We should have a system in place to notice this , and change whatever's happening to cause it.

6. Add the ability to use OpenRouter as an LLM interface instead of ollama.
