import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataTable, type DataTableColumn } from "./DataTable";

interface Row {
  id: string;
  name: string;
  count: number;
}

const columns: DataTableColumn<Row>[] = [
  { key: "name", header: "Name", render: (row) => row.name },
  { key: "count", header: "Count", align: "right", render: (row) => String(row.count) },
];

describe("DataTable", () => {
  it("renders a caption and one row per item", () => {
    const rows: Row[] = [
      { id: "1", name: "member", count: 26 },
      { id: "2", name: "claim", count: 140 },
    ];
    render(<DataTable<Row> columns={columns} rows={rows} getRowKey={(r) => r.id} caption="Test table" />);

    expect(screen.getByText("Test table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    expect(screen.getByText("member")).toBeInTheDocument();
    expect(screen.getByText("140")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(3); // 1 header + 2 body rows
  });

  it("renders the empty message instead of a table when there are no rows", () => {
    render(<DataTable<Row> columns={columns} rows={[]} getRowKey={(r) => r.id} caption="Test table" emptyMessage="Nothing here." />);
    expect(screen.getByText("Nothing here.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
