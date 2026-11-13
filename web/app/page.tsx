import Workspace from "@/components/Workspace";

/**
 * The page is a shell. Everything below it fetches in the browser, so
 * `npm run build` does not need the Python service running, and a service that
 * goes down while the page is open shows an error rather than a stale render.
 */
export default function Page() {
  return <Workspace />;
}
