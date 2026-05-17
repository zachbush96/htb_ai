1. Remove past targets from the project completely include from GitHub , and when the app starts, remove past projects too. [.]

2. Create an easier way to launch this from a PwnBox , or disposable linux VM:
    Possible command (Untested) :
           (python -m uvicorn backend.htbmc.app:app --host 127.0.0.1 --port 8010 >/tmp/htbmc_uvicorn.log 2>&1 &) ; sleep 3; curl -sS http://127.0.0.1:8010/healthz; pkill -f 'uvicorn backend.htbmc.app:app' || true; sleep 1; tail -n 20 /tmp/htbmc_uvicorn.log

4. Why does the app.py wihtin the home//root directory seem like a markdown file and not an actual python script? Update the files accordingly. After more checking, a LOT of the files wtihin the root directory of this project seem incorrect. For example I just check the util.py , and it seems like some sort of LLM skill file. Please address all files like this. Make sure changes do not disrupt the running of the actual project.

5. The app.py (backend/htbmc/app.py) within the backend directory is HUGE and hard to understand completely. Break it up into more digestable and modular components. [.]

6. Sometimes it seem's like the local ollama-based LLM will not return actionable next-steps. This becomes an issue when we are constantly reaching out to the LLM for next instructions, burning tokens, and not getting a reasonable response. We should have a system in place to notice this , and change whatever's happening to cause it.

7. Add the ability to use OpenRouter as an LLM interface instead of ollama. [.]
