import { execFileSync } from 'node:child_process'
import path from 'node:path'

export default function globalSetup() {
  const root = path.resolve(import.meta.dirname, '../..')
  execFileSync(path.join(root, '.venv/bin/python'), [path.join(import.meta.dirname, 'make_fixtures.py')], { stdio: 'inherit' })
}
