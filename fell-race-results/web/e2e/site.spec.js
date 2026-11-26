import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

// The browser tests use the same recorded API responses as the unit tests and the API's own
// contract test, so the site is exercised against exactly what the API returns.
const contract = JSON.parse(readFileSync(new URL('../../contract/examples.json', import.meta.url), 'utf8'))

const PAGES = [
  '/',
  '/races',
  '/races/scar-edge-horseshoe',
  '/championship',
  '/runners?q=ruth',
  '/runners/R0090',
  '/ghost?race=scar-edge-horseshoe&season=2026&runners=R0090,R0084',
  '/submit',
  '/no-such-page',
]

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (route.request().method() === 'POST') {
      const auth = route.request().headers().authorization
      if (auth !== 'Bearer hollinbeck-demo-organiser') {
        return route.fulfill({ status: 401, json: { error: { code: 'unauthorised', message: 'organiser token not recognised' } } })
      }
      return route.fulfill({ json: contract.upload.response })
    }
    const body = contract.examples[decodeURIComponent(url.pathname + url.search)]
    return body === undefined
      ? route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'not in the recorded examples' } } })
      : route.fulfill({ json: body })
  })
})

for (const scheme of ['light', 'dark']) {
  test(`every page is accessible and never scrolls sideways: ${scheme}`, async ({ page }) => {
    const errors = []
    page.on('pageerror', (e) => errors.push(e.message))
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' })
    for (const path of PAGES) {
      await page.goto(path)
      await expect(page.locator('h1').first()).toBeVisible()
      await expect(page.locator('.status--loading')).toHaveCount(0)
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth), path).toBeLessThanOrEqual(0)
      const axe = await new AxeBuilder({ page }).analyze()
      expect(axe.violations.map((v) => `${path} ${v.id}: ${v.nodes[0].html}`)).toEqual([])
    }
    expect(errors).toEqual([])
  })
}

test('pick two runners from a results sheet and replay their race', async ({ page }) => {
  await page.goto('/races/scar-edge-horseshoe')
  await page.getByLabel('Women', { exact: true }).check({ force: true })
  await expect(page).toHaveURL(/sex=F/)
  const women = contract.examples['/api/races/scar-edge-horseshoe/results?season=2026&sex=F&page=1&page_size=50'].items
  await page.getByLabel(`Compare ${women[0].name}`).check()
  await page.getByLabel(`Compare ${women[1].name}`).check()
  await page.getByRole('button', { name: /ghost race the two/i }).click()
  await expect(page).toHaveURL(new RegExp(`runners=${women[0].runner_id},${women[1].runner_id}`))
  // That pair is not in the recorded examples, so the page must show its error state...
  await expect(page.getByRole('alert')).toContainText('not in the recorded examples')
  // ...and the recorded pair works from the picker.
  await page.getByLabel('Runner A').fill('R0090')
  await page.getByLabel('Runner B').fill('R0084')
  await page.getByRole('button', { name: 'Race them' }).click()
  const clock = page.getByRole('slider', { name: 'Race clock' })
  await clock.fill('2575')
  await expect(page.getByTestId('gap')).toHaveText(/Hamish leads by \d+ m/)
  await clock.fill('3888')
  await expect(page.getByText('Ewan takes the lead by 2 s at the finish.')).toBeVisible()
  await expect(page.getByText('finished in 1:04:46')).toBeVisible()
})

test('an organiser sends results and sees what was accepted', async ({ page }) => {
  await page.goto('/submit')
  await expect(page.getByText(/A finisher needs 2 times/)).toBeVisible()
  await page.getByRole('button', { name: 'Send results' }).click()
  await expect(page.getByText('The organiser token is required.')).toBeVisible()
  await page.getByLabel('Results').fill('R0012, 13:32, 24:26\nR0031, 17:15, DNF\nR9999, 13:10, 23:08')
  await expect(page.getByText(/Ready to send 3 results/)).toBeVisible()
  await page.getByLabel('Organiser token').fill('wrong')
  await page.getByRole('button', { name: 'Send results' }).click()
  await expect(page.getByRole('alert')).toContainText('not accepted')
  await page.getByLabel('Organiser token').fill('hollinbeck-demo-organiser')
  await page.getByRole('button', { name: 'Send results' }).click()
  await expect(page.getByRole('heading', { name: 'Results received' })).toBeVisible()
  await expect(page.getByText('2 added, 0 corrected, 0 unchanged, 1 not accepted.')).toBeVisible()
})

test('championship filters survive a reload because they live in the address', async ({ page }) => {
  await page.goto('/championship')
  await page.getByLabel('Men', { exact: true }).check({ force: true })
  await page.getByLabel('Age category').selectOption('V40')
  await expect(page).toHaveURL(/sex=M&category=V40/)
  await page.reload()
  await expect(page.getByLabel('Age category')).toHaveValue('V40')
  const firstRow = page.getByRole('region', { name: 'Championship table' }).locator('tbody tr').first()
  await expect(firstRow.locator('td').first()).toHaveText('1')
})

test('keyboard users can skip to content and reach the main navigation', async ({ page, isMobile }) => {
  test.skip(isMobile, 'keyboard journey is checked on desktop')
  await page.goto('/')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: /Hollinbeck/ })).toBeFocused()
  await page.keyboard.press('Tab')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/races$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Races' })).toBeFocused()
})

test('screenshots for the README', async ({ page, isMobile }) => {
  test.skip(!process.env.SCREENSHOTS, 'set SCREENSHOTS=1 to refresh docs/ images')
  const shots = isMobile
    ? [['/ghost?race=scar-edge-horseshoe&season=2026&runners=R0090,R0084', 'phone-ghost', 'light', '2575']]
    : [
        ['/', 'home', 'light'],
        ['/ghost?race=scar-edge-horseshoe&season=2026&runners=R0090,R0084', 'ghost', 'light', '2575'],
        ['/championship?sex=F', 'championship-dark', 'dark'],
      ]
  for (const [path, name, scheme, clock] of shots) {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' })
    await page.goto(path)
    await expect(page.locator('.status--loading')).toHaveCount(0)
    if (!isMobile) await page.setViewportSize({ width: 1280, height: 1000 })
    if (clock) {
      await page.getByRole('slider', { name: 'Race clock' }).fill(clock)
      await page.evaluate(() => document.activeElement.blur())
      await page.locator('h1').scrollIntoViewIfNeeded()
      await page.evaluate(() => window.scrollTo(0, isFinite(innerWidth) && innerWidth < 600 ? 300 : 50))
    }
    await page.waitForTimeout(400) // let the browser paint the moved markers
    await page.screenshot({ path: `../docs/${name}.jpg`, type: 'jpeg', quality: 82 })
  }
})
