"""Vault-local OpenCode plugin around the single installed lifecycle adapter."""
import json
import os
import sys

WRITE_TOOLS = ('edit', 'write', 'patch', 'apply_patch', 'multiedit')

PLUGIN = r'''// Beyin V3 OpenCode plugin; installer-owned, removed by rollback and uninstall.
import { execFile } from "node:child_process"
import { readFileSync } from "node:fs"
import { dirname, isAbsolute, join } from "node:path"
import { fileURLToPath } from "node:url"

const PYTHON = process.env.BEYIN_PYTHON || __PYTHON__
const VAULT = dirname(dirname(dirname(fileURLToPath(import.meta.url))))
const HOOK = join(VAULT, ".claude", "scripts", "beyin_v3_hook.py")
const WRITE_TOOLS = new Set(__WRITE_TOOLS__)

function runtimeState() {
  try {
    const data = JSON.parse(readFileSync(join(VAULT, ".beyin-runtime.json"), "utf8"))
    return typeof data?.state === "string" && isAbsolute(data.state) ? data.state : null
  } catch {
    return null
  }
}

function runHook(state, payload) {
  // Fail open: any transport failure means no context, never a broken OpenCode turn.
  return new Promise((resolve) => {
    try {
      const child = execFile(PYTHON, [HOOK, "--vault", VAULT, "--state", state, "--harness", "opencode"],
        { timeout: __TIMEOUT__, maxBuffer: 4 * 1024 * 1024, windowsHide: true,
          env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONDONTWRITEBYTECODE: "1" } },
        (error, stdout) => {
          try {
            const text = error ? "" : JSON.parse(String(stdout || "{}"))?.hookSpecificOutput?.additionalContext
            resolve(typeof text === "string" ? text : "")
          } catch {
            resolve("")
          }
        })
      child.on("error", () => resolve(""))
      child.stdin.on("error", () => {})
      child.stdin.end(JSON.stringify(payload))
    } catch {
      resolve("")
    }
  })
}

export const BeyinV3 = async ({ client } = {}) => {
  const state = runtimeState()
  if (!state) return {}
  const sessions = new Map()
  const send = (event, id, prompt) => runHook(state, { hook_event_name: event, session_id: id, ...(prompt === undefined ? {} : { prompt }) })
  const tracked = (id) => {
    const info = typeof id === "string" && id ? sessions.get(id) : undefined
    return info && !info.child ? info : undefined
  }

  async function open(id) {
    if (!sessions.has(id)) {
      let child = false
      try {
        child = Boolean((await client?.session?.get?.({ path: { id } }))?.data?.parentID)
      } catch {}
      // Sub-agent sessions never submit receipts; tracking them would report false gaps.
      sessions.set(id, { child, start: null, turn: "" })
    }
    return sessions.get(id)
  }

  return {
    "chat.message": async (input, output) => {
      const id = input?.sessionID
      if (typeof id !== "string" || !id) return
      const info = await open(id)
      if (info.child) return
      const prompt = (output?.parts || [])
        .filter((part) => part?.type === "text" && !part.synthetic && typeof part.text === "string")
        .map((part) => part.text).join("\n")
      if (info.start === null) info.start = await send("SessionStart", id, prompt)
      else info.turn = await send("UserPromptSubmit", id, prompt)
    },
    // The only request-time injection channel; SessionStart context stays for the whole session.
    "experimental.chat.system.transform": async (input, output) => {
      const info = tracked(input?.sessionID)
      if (info && Array.isArray(output?.system))
        for (const text of [info.start, info.turn]) if (text) output.system.push(text)
    },
    "tool.execute.after": async (input) => {
      if (tracked(input?.sessionID) && WRITE_TOOLS.has(input?.tool)) await send("PostToolUse", input.sessionID)
    },
    "experimental.session.compacting": async (input) => {
      if (tracked(input?.sessionID)) await send("PreCompact", input.sessionID)
    },
    event: async ({ event } = {}) => {
      if (event?.type === "session.idle" && tracked(event.properties?.sessionID)) {
        await send("Stop", event.properties.sessionID)
      } else if (event?.type === "session.deleted") {
        const id = event.properties?.info?.id
        if (tracked(id)) await send("SessionEnd", id)
        sessions.delete(id)
      }
    },
  }
}
'''


def plan_plugin(vault, state):
    """Return plugin bytes; vault comes from the file location and state from .beyin-runtime.json."""
    if any(char in sys.executable for char in '\r\n\x00'):
        raise ValueError('Unsupported interpreter path')
    source = (PLUGIN.replace('__PYTHON__', json.dumps(sys.executable))
              .replace('__TIMEOUT__', '20000' if os.name == 'nt' else '6000')
              .replace('__WRITE_TOOLS__', json.dumps(list(WRITE_TOOLS))))
    return {'.opencode/plugins/beyin-v3.js': source.encode('utf-8')}
