/** Frontend contract (CLAUDE.md §7.10): env-injected config, no key ever committed.
 *  VITE_ vars come from Amplify environment variables (or a local .env for dev). */

export const AWS_REGION: string = import.meta.env.VITE_AWS_REGION ?? 'ap-south-1'
export const API_URL: string = import.meta.env.VITE_API_URL ?? ''
export const LOCATION_API_KEY: string = import.meta.env.VITE_LOCATION_API_KEY ?? ''

/** Map centre = Karol Bagh centroid — mirrors pipeline/config.py COVERAGE_CENTROID. */
export const AREA_CENTRE: [number, number] = [77.193, 28.6495]
