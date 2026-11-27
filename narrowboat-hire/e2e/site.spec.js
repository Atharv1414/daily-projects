import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

const PAGES = [
  '/',
  '/routes',
  '/routes?nights=4&pace=gentle&boat=heron',
  '/fleet',
  '/fleet/kestrel',
  '/book?boat=dabchick&nights=7',
  '/book?boat=dabchick&nights=7&step=2',
  '/first-time',
  '/no-such-page',
]

const sideways = (page) =>
  page.evaluate(() => Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth, document.documentElement.scrollWidth - innerWidth))

for (const scheme of ['light', 'dark']) {
  test(`every page is accessible and never scrolls sideways: ${scheme}`, async ({ page }) => {
    const errors = []
    page.on('pageerror', (e) => errors.push(e.message))
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' })
    for (const path of PAGES) {
      await page.goto(path)
      await expect(page.locator('h1').first()).toBeVisible()
      expect(await sideways(page), path).toBeLessThanOrEqual(0)
      const axe = await new AxeBuilder({ page }).analyze()
      expect(axe.violations.map((v) => `${path} ${v.id}: ${v.nodes[0].html}`)).toEqual([])
    }
    expect(errors).toEqual([])
  })
}

test('plan a route, then book the boat for it end to end', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('link', { name: 'Plan a route' }).first().click()
  await expect(page.getByRole('heading', { level: 1, name: 'Plan a route' })).toBeFocused()

  await page.getByLabel('How long').selectOption('4')
  await page.getByLabel('Boat').selectOption('dabchick')
  await expect(page).toHaveURL(/nights=4/)
  await expect(page.getByRole('table')).toBeVisible()
  const routeName = await page.locator('#chosen-heading').textContent()

  await page.getByRole('link', { name: 'Book Dabchick for this route' }).click()
  await expect(page.getByText(`Planned route: ${routeName}`)).toBeVisible()
  await page.locator('.chip').first().click()
  await page.getByRole('button', { name: 'Continue to extras' }).click()
  await page.getByLabel(/A dog/).check()
  await page.getByRole('button', { name: 'Continue to your crew' }).click()

  await page.getByRole('button', { name: 'Check the booking' }).click()
  await expect(page.getByRole('alert')).toBeFocused()
  await expect(page.getByRole('alert')).toContainText('There are 7 problems')

  await page.getByLabel('Lead name').fill('Asha Rao')
  await page.getByLabel('Email').fill('asha@example.com')
  await page.getByLabel(/Mobile number/).fill('+44 7700 900123')
  await page.getByLabel(/How many people/).fill('3')
  await page.getByLabel(/steered a narrowboat/).selectOption('some')
  await page.getByLabel(/An adult will be at the tiller/).check()
  await page.getByLabel(/hire terms/).check()
  await page.getByRole('button', { name: 'Check the booking' }).click()

  await expect(page.getByRole('heading', { name: 'Check and confirm' })).toBeVisible()
  expect(page.url()).not.toContain('asha')
  await page.getByRole('button', { name: 'Confirm booking (demo)' }).click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('See you at the wharf, Asha')
  await expect(page.getByText(/^Reference KL-/)).toBeVisible()
})

test('the lock guide can be worked with the keyboard alone', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/first-time')
  const next = page.getByRole('button', { name: 'Next step' })
  await next.focus()
  for (let i = 0; i < 6; i++) await page.keyboard.press('Enter')
  await expect(page.getByText('Step 7 of 7')).toBeVisible()
  await expect(next).toBeDisabled()
})
