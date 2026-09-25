import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page not found" />
      <p>
        <Link to="/">Return to the dashboard</Link>.
      </p>
    </>
  );
}
