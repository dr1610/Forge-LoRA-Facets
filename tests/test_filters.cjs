// Run with: node tests/test_filters.cjs (no npm dependencies).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = {window: {}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../javascript/lora-facets.js'), 'utf8'), context);
const matches = context.window.loraFacetsMatches;
const state = {genres: new Set(), tags: new Set(), bases: new Set(), mode: 'and'};
const item = {base_model: 'Anima', genres: ['character'], tags: ['blue_hair', 'anime']};
assert.equal(matches(item, state), true);
state.bases = new Set(['Pony']);
assert.equal(matches(item, state), false);
state.bases.add('Anima');
assert.equal(matches(item, state), true); // Model choices are OR.
state.genres.add('clothing');
assert.equal(matches(item, state), false); // Different facets are AND.
state.genres.clear(); state.tags.add('blue hair');
assert.equal(matches(item, state), true);
state.tags.add('winter');
assert.equal(matches(item, state), false);
state.mode = 'or';
assert.equal(matches(item, state), true);
state.bases = new Set(['Pony']);
assert.equal(matches(item, state), false); // Tag OR does not bypass the model filter.
state.tags.clear(); state.bases = new Set(['不明']);
assert.equal(matches({...item, base_model: ''}, state), true);
assert.equal(matches({...item, base_model: null}, state), true);
assert.equal(matches({...item, base_model: 'SDXL 1.0'}, state), false);
console.log('Filter tests passed');
