// The waterways around Marrowby Wharf. Every place, canal and pub here is invented.
// Coordinates are for the schematic map (1000 x 640). Elevations are feet above sea level.

export const BASE = 'marrowby'

export const WATERWAYS = {
  ashlock: { name: 'Ashlock Canal', gauge: 'broad', note: 'Broad locks: two boats can share each chamber.' },
  tenbridge: { name: 'Tenbridge Navigation', gauge: 'broad', note: 'Part canal, part river. Check the level boards after heavy rain.' },
  hollins: { name: 'Hollins Arm', gauge: 'narrow', note: 'Narrow locks built for 57 ft boats.' },
  saltmoor: { name: 'Saltmoor Cut', gauge: 'broad', note: 'Lock-free and lined with moorings.' },
}

export const PLACES = [
  { id: 'marrowby', name: 'Marrowby Wharf', x: 470, y: 470, elevation: 210, mooring: true, winding: true, base: true, services: ['water', 'pump-out', 'shop', 'pub'], pub: "The Lock Keeper's Cat" },
  { id: 'saltmoor', name: 'Saltmoor Junction', x: 640, y: 420, elevation: 210, mooring: true, winding: true, services: ['water'], pub: 'The Three Paddles' },
  { id: 'ashlock-bottom', name: 'Ashlock Bottom Lock', x: 760, y: 300, elevation: 222, mooring: true, winding: false, services: ['water'] },
  { id: 'ashlock-top', name: 'Ashlock Top', x: 800, y: 190, elevation: 306, mooring: true, winding: true, services: ['water', 'pump-out'], pub: 'The Summit Inn' },
  { id: 'kiln-green', name: 'Kiln Green', x: 930, y: 110, elevation: 330, mooring: true, winding: true, services: [], pub: 'The Brick Kiln' },
  { id: 'quarrington', name: 'Quarrington Wharf', x: 560, y: 120, elevation: 306, mooring: true, winding: true, services: ['water', 'shop'] },
  { id: 'larkspur', name: 'Larkspur Basin', x: 330, y: 60, elevation: 306, mooring: true, winding: true, services: ['water'], pub: 'The Heron & Pike' },
  { id: 'tenbridge-jn', name: 'Tenbridge Junction', x: 400, y: 200, elevation: 306, mooring: true, winding: true, services: [] },
  { id: 'cobbs-mill', name: "Cobb's Mill", x: 230, y: 290, elevation: 258, mooring: true, winding: false, services: ['water'], pub: 'The Millrace' },
  { id: 'tenbridge', name: 'Tenbridge', x: 260, y: 450, elevation: 222, mooring: true, winding: true, services: ['water', 'pump-out', 'shop', 'pub'], pub: 'The Navigation' },
  { id: 'merestone', name: 'Merestone Lakes', x: 90, y: 560, elevation: 222, mooring: true, winding: true, services: [] },
  { id: 'hollins-jn', name: 'Hollins Junction', x: 520, y: 590, elevation: 210, mooring: true, winding: true, services: ['water'] },
  { id: 'wrenfold', name: 'Wrenfold', x: 720, y: 600, elevation: 234, mooring: true, winding: false, services: [], pub: 'The Wren' },
  { id: 'upper-hollins', name: 'Upper Hollins', x: 880, y: 520, elevation: 262, mooring: true, winding: true, services: ['water'] },
]

// maxLength is the longest boat the locks or bends can take, in feet.
export const REACHES = [
  { id: 'r1', from: 'marrowby', to: 'saltmoor', waterway: 'ashlock', miles: 4, locks: 0, maxLength: 70 },
  { id: 'r2', from: 'saltmoor', to: 'ashlock-bottom', waterway: 'ashlock', miles: 7, locks: 1, maxLength: 70 },
  { id: 'r3', from: 'ashlock-bottom', to: 'ashlock-top', waterway: 'ashlock', miles: 1.5, locks: 12, flight: 'Ashlock Flight', maxLength: 70, labelAt: [818, 262] },
  { id: 'r4', from: 'ashlock-top', to: 'kiln-green', waterway: 'ashlock', miles: 3, locks: 2, maxLength: 70 },
  { id: 'r5', from: 'ashlock-top', to: 'quarrington', waterway: 'ashlock', miles: 9, locks: 0, maxLength: 70, tunnel: { name: 'Fenny Tunnel', yards: 1320 }, labelAt: [652, 196] },
  { id: 'r6', from: 'quarrington', to: 'larkspur', waterway: 'ashlock', miles: 7, locks: 0, maxLength: 70, note: 'The Long Pound: seven lock-free miles.' },
  { id: 'r7', from: 'quarrington', to: 'tenbridge-jn', waterway: 'tenbridge', miles: 6, locks: 0, maxLength: 70 },
  { id: 'r8', from: 'tenbridge-jn', to: 'cobbs-mill', waterway: 'tenbridge', miles: 11, locks: 8, maxLength: 70 },
  { id: 'r9', from: 'cobbs-mill', to: 'tenbridge', waterway: 'tenbridge', miles: 9, locks: 6, maxLength: 70, river: true },
  { id: 'r10', from: 'tenbridge', to: 'merestone', waterway: 'tenbridge', miles: 5, locks: 0, maxLength: 70, river: true },
  { id: 'r11', from: 'tenbridge', to: 'saltmoor', waterway: 'tenbridge', miles: 7, locks: 1, maxLength: 70 },
  { id: 'r12', from: 'marrowby', to: 'hollins-jn', waterway: 'saltmoor', miles: 3, locks: 0, maxLength: 70 },
  { id: 'r13', from: 'hollins-jn', to: 'wrenfold', waterway: 'hollins', miles: 5, locks: 3, maxLength: 57 },
  { id: 'r14', from: 'wrenfold', to: 'upper-hollins', waterway: 'hollins', miles: 4, locks: 4, maxLength: 57, aqueduct: 'Wren Aqueduct', labelAt: [780, 612] },
  { id: 'r15', from: 'upper-hollins', to: 'saltmoor', waterway: 'hollins', miles: 6, locks: 4, maxLength: 57, flight: 'Sallow Locks', labelAt: [742, 448] },
]

export const placeById = Object.fromEntries(PLACES.map((p) => [p.id, p]))
export const reachById = Object.fromEntries(REACHES.map((r) => [r.id, r]))
