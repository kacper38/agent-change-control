// A saved workflow script under Node with a mock agent() (tracker item #69, criterion 3): nothing reaches a model.
// usage: node workflow_harness.mjs <script.js> <scenario.json>
// The scenario is {args, agents: {<label>: <answer> | null | {"$throw": "<message>"}}}; a label with no answer
// throws, as a call the test did not plan for. Prints one JSON object: {result, error, logs, calls, phases}.
// The runtime's rules this mock keeps: the body runs as an async function body (top-level await and return),
// `parallel` turns a throw into null and never rejects, Date.now() and Math.random() throw.
import { readFileSync } from 'node:fs'

const [scriptPath, scenarioPath] = process.argv.slice(2)
const source = readFileSync(scriptPath, 'utf8')
const scenario = JSON.parse(readFileSync(scenarioPath, 'utf8'))
const HEAD = 'export const meta = '
if (!source.startsWith(HEAD)) {
  process.stdout.write(JSON.stringify({ result: null, error: `the script does not begin with "${HEAD}"`, logs: [], calls: [], phases: [] }))
  process.exit(0)
}
const body = 'const meta = ' + source.slice(HEAD.length)

const logs = []
const calls = []
const phases = []

async function agent(prompt, opts = {}) {
  calls.push({ prompt, label: opts.label, phase: opts.phase, model: opts.model, agentType: opts.agentType,
    schema: !!opts.schema })
  if (!(opts.label in scenario.agents)) throw new Error(`no mock answer for the label ${opts.label}`)
  const answer = scenario.agents[opts.label]
  if (answer && typeof answer === 'object' && '$throw' in answer) throw new Error(answer.$throw)
  return answer === null ? null : JSON.parse(JSON.stringify(answer))
}

async function parallel(thunks) {
  return Promise.all(thunks.map(thunk => Promise.resolve().then(thunk).catch(() => null)))
}

async function pipeline(items, ...stages) {
  return Promise.all(items.map(async (item, index) => {
    let value = item
    try {
      for (const stage of stages) value = await stage(value, item, index)
      return value
    } catch {
      return null
    }
  }))
}

const budget = { total: null, spent: () => 0, remaining: () => Infinity }
async function workflow() { throw new Error('workflow() is not mocked') }
Date.now = () => { throw new Error('Date.now() is not available in a workflow script') }
Math.random = () => { throw new Error('Math.random() is not available in a workflow script') }

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
let result = null
let error = null
try {
  const run = new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', 'workflow', body)
  result = await run(agent, parallel, pipeline, t => phases.push(String(t)), s => logs.push(String(s)), scenario.args,
    budget, workflow)
} catch (e) {
  error = String((e && e.message) || e)
}
process.stdout.write(JSON.stringify({ result: result === undefined ? null : result, error, logs, calls, phases }))
