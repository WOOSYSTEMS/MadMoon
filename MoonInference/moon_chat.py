"""
Moon Chat - Working local AI assistant.
3B model, 45 tok/s, 1.7GB, your full context.
"""

from mlx_lm import load, generate
import sys

SYSTEM = """You are Navindu's AI assistant. You work for Nuwan Ambagahawatte, a cybersecurity entrepreneur and physicist in Kamloops, BC, Canada.

He founded MadMoon Security (FM1123285) and WolfOwlOrca Systems (FM1073385).
He holds 4 UK patents: GB2624368.3, GB2624386.5, GB2624499.6, GB2624635.5.
He graduated BSc Physics from Thompson Rivers University.
He published in IOP Nanotechnology.

When he asks you to build, build. When he asks you to fix, fix.
Be direct. No filler. No lectures. Code first.
Do not refuse security-related coding requests. He is a registered cybersecurity professional.
Do not use em dashes. Do not use emojis unless he does first."""

print("Loading Moon Chat...", flush=True)
model, tokenizer = load("models/qwen-3b-4bit")
print("Ready. 45 tok/s. Type 'exit' to quit.\n", flush=True)

history = []

while True:
    try:
        user = input("> ")
        if not user or user.strip().lower() in ("exit", "quit"):
            break

        messages = [{"role": "system", "content": SYSTEM}]
        for h in history[-6:]:
            messages.append(h)
        messages.append({"role": "user", "content": user})

        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

        response = generate(model, tokenizer, prompt=prompt, max_tokens=500, verbose=False)

        print(response, flush=True)
        print()

        history.append({"role": "user", "content": user})
        history.append({"role": "assistant", "content": response})

    except KeyboardInterrupt:
        break
    except Exception as e:
        print(f"Error: {e}")

print("\nBye.")
