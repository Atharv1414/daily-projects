import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

const PAGES = ['/', '/methods', '/methods/plain-bob-minor', '/methods/cambridge-major?bell=5', '/methods/stedman-doubles', '/practice', '/appeal', '/visit', '/nowhere']

for (const scheme of ['light', 'dark']) {
  test(`every page is accessible and never scrolls sideways: ${scheme}`, async ({ page }) => {
    test.setTimeout(90_000)
    const errors = []
    page.on('pageerror', (e) => errors.push(e.message))
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' })
    for (const path of PAGES) {
      await page.goto(path)
      await expect(page.locator('h1').first()).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth), path).toBeLessThanOrEqual(0)
      const axe = await new AxeBuilder({ page }).analyze()
      expect(axe.violations.map((v) => `${path} ${v.id}: ${v.nodes[0].html} ${v.nodes[0].failureSummary}`)).toEqual([])
    }
    expect(errors).toEqual([])
  })
}

test('fits a 360px screen', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 })
  for (const path of PAGES) {
    await page.goto(path)
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth), path).toBeLessThanOrEqual(0)
  }
})

test('the front page comes round at its foot', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('Scroll to ring 112 changes.')).toBeVisible()
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight / 3))
  await expect(page.getByText(/^Change \d+ of 112$/)).toBeVisible()
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
  await expect(page.getByText('The bells have come round.')).toBeVisible()
})

test('call a touch, hear it and share it', async ({ page }) => {
  await page.goto('/methods/plain-bob-doubles')
  await page.getByRole('button', { name: 'All 120' }).click()
  await expect(page.getByText('120 changes')).toBeVisible()
  await expect(page.getByText('It comes round.')).toBeVisible()
  await page.getByRole('button', { name: 'Ring it' }).click()
  await expect(page.getByText(/Change [1-9]\d*: your bell is/)).toBeVisible()
  await page.getByRole('button', { name: 'Stand' }).click()
  await page.reload()
  await expect(page.getByText('120 changes')).toBeVisible()
})

test('ring a piece with the keyboard and get a verdict', async ({ page }) => {
  test.setTimeout(90_000)
  await page.goto('/practice?bell=1&speed=steady')
  const start = page.getByRole('button', { name: 'Look to' })
  await start.click()
  for (let i = 0; i < 12; i++) {
    await expect(page.getByRole('list', { name: `Row ${i + 1} of 12` })).toBeVisible({ timeout: 8000 })
    await page.keyboard.press('Space')
  }
  await expect(page.getByRole('heading', { name: /% struck/ })).toBeVisible({ timeout: 15_000 })
  await expect(page.locator('.striking li')).toHaveCount(12)
  expect(await page.locator('.striking__missed').count()).toBeLessThan(4)
})

test('book a rope from start to finish', async ({ page }) => {
  await page.goto('/visit')
  await page.getByRole('button', { name: 'Book' }).click()
  await expect(page.getByRole('alert')).toBeFocused()
  await page.locator('.visit__dates label').nth(1).click()
  await page.locator('.visit__ropes label:not(.is-taken)').first().click()
  await page.getByLabel('Your name').fill('Asha Rao')
  await page.getByLabel('Email').fill('asha@example.org')
  await page.getByLabel('Age').fill('34')
  await page.getByRole('button', { name: /Book rope/ }).click()
  await expect(page.getByRole('heading', { name: /is yours, Asha Rao/ })).toBeVisible()
})

test('pledge with the keyboard alone', async ({ page }) => {
  await page.goto('/appeal')
  await page.getByRole('button', { name: /Old Constant/ }).focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/bell=7/)
  await page.getByLabel(/Name for/).fill('A Friend')
  await page.getByLabel('Email').fill('friend@example.org')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Thank you, A Friend' })).toBeVisible()
})
