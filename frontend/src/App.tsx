/**
 * Root application component: mounts the route table
 * (`src/routes/index.tsx`), which in turn renders `AppShell`
 * (navigation + outlet) around every page in `src/pages/`.
 *
 * See ARCHITECTURE.md section 2.5 and docs/adr/0008-frontend-stack.md:
 * this app talks only to the control-plane REST API under /api — never
 * directly to storage, the metadata database, or Spark. Every page
 * fetches real data through `src/api/` (see `src/api/README.md`); none
 * of them fabricate or mock API responses.
 */
import { RouterProvider } from "react-router-dom";
import { router } from "@/routes";

export default function App() {
  return <RouterProvider router={router} />;
}
