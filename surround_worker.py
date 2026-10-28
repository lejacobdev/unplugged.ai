"""Runs inside the ACE-Step environment (vendor/ACE-Step-1.5/.venv). Started by surround.py, never by hand.

Protocol: one JSON request per stdin line; answers are stdout lines that start with the MARK prefix, everything else
(ACE-Step's own logging) is ignored by the parent.
  request : {"id", "caption", "lyrics", "duration", "seed", "out_dir"}
  answers : {"id", "event": "loading" | "ready" | "composing" | "done" | "error", ...}
"""
import json
import os
import sys
import time

MARK = "@@SURROUND@@ "
ACE = os.path.dirname(os.path.abspath(__file__)) + "/vendor/ACE-Step-1.5"
sys.path.insert(0, ACE)
os.chdir(ACE)
os.environ.setdefault("ACESTEP_LM_BACKEND", "mlx")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def say(**kw):
    sys.stdout.write(MARK + json.dumps(kw) + "\n")
    sys.stdout.flush()


def main():
    say(event="loading")
    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music
    from acestep.llm_inference import LLMHandler

    t = time.time()
    dit = AceStepHandler()
    msg, ok = dit.initialize_service(project_root=ACE, config_path="acestep-v15-turbo", device="auto", offload_to_cpu=False)
    if not ok:
        say(event="error", message="Could not load the music model: " + str(msg))
        return
    lm = LLMHandler()
    msg, ok = lm.initialize(checkpoint_dir=os.path.join(ACE, "checkpoints"), lm_model_path="acestep-5Hz-lm-1.7B", backend="mlx", device="auto", offload_to_cpu=False, dtype=None)
    if not ok:
        say(event="error", message="Could not load the music language model: " + str(msg))
        return
    say(event="ready", load_seconds=round(time.time() - t, 1))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        rid = req.get("id")
        try:
            say(id=rid, event="composing")
            lyrics = (req.get("lyrics") or "").strip() or "[Instrumental]"
            params = GenerationParams(task_type="text2music", thinking=True, caption=req["caption"], lyrics=lyrics,
                                      duration=float(req["duration"]), inference_steps=8, seed=int(req.get("seed", -1)),
                                      vocal_language=req.get("language") or "en")
            t = time.time()
            res = generate_music(dit, lm, params, GenerationConfig(batch_size=1, audio_format="wav"), save_dir=req["out_dir"])
            if not res.success or not res.audios:
                say(id=rid, event="error", message=str(res.error or "the model returned no audio"))
                continue
            a = res.audios[0]
            say(id=rid, event="done", path=a["path"], seconds=round(time.time() - t, 1), seed=a.get("params", {}).get("seed"))
        except Exception as e:  # keep the worker alive for the next request
            say(id=rid, event="error", message=f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
