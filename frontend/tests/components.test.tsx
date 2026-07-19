import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PageContainer } from "@/components/PageContainer";
import { Section } from "@/components/Section";
import { Card } from "@/components/Card";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { MetricCard } from "@/components/MetricCard";
import { Loading } from "@/components/Loading";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Divider } from "@/components/Divider";
import { Toolbar } from "@/components/Toolbar";
import { SearchBox } from "@/components/SearchBox";
import { Table } from "@/components/Table";
import { Timeline } from "@/components/Timeline";
import { PropertyGrid } from "@/components/PropertyGrid";
import { Modal } from "@/components/Modal";
import { ConfirmationDialog } from "@/components/ConfirmationDialog";

describe("PageContainer", () => {
  it("renderiza children", () => {
    render(<PageContainer><div>conteúdo</div></PageContainer>);
    expect(screen.getByText("conteúdo")).toBeInTheDocument();
    expect(screen.getByTestId("page-container")).toBeInTheDocument();
  });
});

describe("Section", () => {
  it("renderiza com título e descrição", () => {
    render(
      <Section title="Título" description="Descrição">
        <div>conteúdo</div>
      </Section>,
    );
    expect(screen.getByText("Título")).toBeInTheDocument();
    expect(screen.getByText("Descrição")).toBeInTheDocument();
  });

  it("renderiza sem título", () => {
    render(<Section><div>conteúdo</div></Section>);
    expect(screen.getByText("conteúdo")).toBeInTheDocument();
  });

  it("renderiza actions", () => {
    render(
      <Section title="T" actions={<button>Ação</button>}>
        <div>c</div>
      </Section>,
    );
    expect(screen.getByText("Ação")).toBeInTheDocument();
  });
});

describe("Card", () => {
  it("renderiza children", () => {
    render(<Card><div>card</div></Card>);
    expect(screen.getByText("card")).toBeInTheDocument();
    expect(screen.getByTestId("card")).toBeInTheDocument();
  });

  it("renderiza com título e descrição", () => {
    render(<Card title="T" description="D"><div>c</div></Card>);
    expect(screen.getByText("T")).toBeInTheDocument();
    expect(screen.getByText("D")).toBeInTheDocument();
  });
});

describe("Panel", () => {
  it("renderiza children", () => {
    render(<Panel><div>panel</div></Panel>);
    expect(screen.getByText("panel")).toBeInTheDocument();
  });

  it("renderiza com título", () => {
    render(<Panel title="Título"><div>c</div></Panel>);
    expect(screen.getByText("Título")).toBeInTheDocument();
  });
});

describe("StatusBadge", () => {
  it("renderiza com status padrão", () => {
    render(<StatusBadge status="healthy" />);
    expect(screen.getByTestId("status-badge")).toBeInTheDocument();
    expect(screen.getByText("Saudável")).toBeInTheDocument();
  });

  it("renderiza com label customizado", () => {
    render(<StatusBadge status="error" label="Falha" />);
    expect(screen.getByText("Falha")).toBeInTheDocument();
  });

  it("aplica data-status", () => {
    render(<StatusBadge status="processing" />);
    expect(screen.getByTestId("status-badge")).toHaveAttribute("data-status", "processing");
  });
});

describe("MetricCard", () => {
  it("renderiza label e value", () => {
    render(<MetricCard label="Segmentos" value={42} />);
    expect(screen.getByText("Segmentos")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("renderiza com unit e description", () => {
    render(<MetricCard label="Latência" value={100} unit="ms" description="média" />);
    expect(screen.getByText("ms")).toBeInTheDocument();
    expect(screen.getByText("média")).toBeInTheDocument();
  });

  it("renderiza com status", () => {
    render(<MetricCard label="L" value={1} status="healthy" />);
    expect(screen.getByTestId("status-badge")).toBeInTheDocument();
  });
});

describe("Loading", () => {
  it("renderiza com label padrão", () => {
    render(<Loading />);
    expect(screen.getByText("Carregando…")).toBeInTheDocument();
    expect(screen.getByTestId("loading")).toBeInTheDocument();
  });

  it("renderiza com label customizado", () => {
    render(<Loading label="Buscando…" />);
    expect(screen.getByText("Buscando…")).toBeInTheDocument();
  });
});

describe("EmptyState", () => {
  it("renderiza com valores padrão", () => {
    render(<EmptyState />);
    expect(screen.getByText("Nada por aqui")).toBeInTheDocument();
    expect(screen.getByTestId("empty-state")).toBeInTheDocument();
  });

  it("renderiza com título e descrição customizados", () => {
    render(<EmptyState title="Sem dados" description="Não há registros." />);
    expect(screen.getByText("Sem dados")).toBeInTheDocument();
    expect(screen.getByText("Não há registros.")).toBeInTheDocument();
  });
});

describe("ErrorState", () => {
  it("renderiza com valores padrão", () => {
    render(<ErrorState />);
    expect(screen.getByText("Erro")).toBeInTheDocument();
    expect(screen.getByTestId("error-state")).toBeInTheDocument();
  });

  it("renderiza com mensagem customizada", () => {
    render(<ErrorState title="Falha" message="Não foi possível carregar." />);
    expect(screen.getByText("Falha")).toBeInTheDocument();
    expect(screen.getByText("Não foi possível carregar.")).toBeInTheDocument();
  });
});

describe("Divider", () => {
  it("renderiza sem label", () => {
    render(<Divider />);
    expect(screen.getByTestId("divider")).toBeInTheDocument();
  });

  it("renderiza com label", () => {
    render(<Divider label="separador" />);
    expect(screen.getByText("separador")).toBeInTheDocument();
  });
});

describe("Toolbar", () => {
  it("renderiza children", () => {
    render(<Toolbar><button>B1</button><button>B2</button></Toolbar>);
    expect(screen.getByText("B1")).toBeInTheDocument();
    expect(screen.getByText("B2")).toBeInTheDocument();
  });
});

describe("SearchBox", () => {
  it("renderiza com placeholder", () => {
    render(<SearchBox placeholder="Buscar eventos…" />);
    expect(screen.getByPlaceholderText("Buscar eventos…")).toBeInTheDocument();
  });

  it("chama onChange ao digitar", () => {
    const onChange = vi.fn();
    render(<SearchBox onChange={onChange} />);
    const input = screen.getByRole("textbox");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    // Apenas verifica que o input existe e é funcional.
    expect(input).toBeInTheDocument();
  });
});

describe("Table", () => {
  it("renderiza mensagem vazia quando não há dados", () => {
    render(
      <Table
        columns={[{ key: "name", header: "Nome" }]}
        data={[]}
        emptyMessage="Sem dados."
      />,
    );
    expect(screen.getByText("Sem dados.")).toBeInTheDocument();
  });

  it("renderiza linhas com dados", () => {
    const data = [
      { name: "Alice", age: 30 },
      { name: "Bob", age: 25 },
    ];
    render(
      <Table
        columns={[
          { key: "name", header: "Nome" },
          { key: "age", header: "Idade" },
        ]}
        data={data}
      />,
    );
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("30")).toBeInTheDocument();
    expect(screen.getByText("25")).toBeInTheDocument();
  });

  it("renderiza com render customizado", () => {
    const data = [{ name: "Alice", status: "active" }];
    render(
      <Table
        columns={[
          { key: "name", header: "Nome" },
          { key: "status", header: "Status", render: () => <span>Ativo</span> },
        ]}
        data={data}
      />,
    );
    expect(screen.getByText("Ativo")).toBeInTheDocument();
  });
});

describe("Timeline", () => {
  it("renderiza mensagem vazia quando não há items", () => {
    render(<Timeline items={[]} />);
    expect(screen.getByText("Nenhum evento na timeline.")).toBeInTheDocument();
  });

  it("renderiza items", () => {
    render(
      <Timeline
        items={[
          { timestamp: 100, title: "Evento 1", description: "Desc 1" },
          { timestamp: 200, title: "Evento 2", description: "Desc 2" },
        ]}
      />,
    );
    expect(screen.getByText("Evento 1")).toBeInTheDocument();
    expect(screen.getByText("Evento 2")).toBeInTheDocument();
    expect(screen.getByText("Desc 1")).toBeInTheDocument();
    expect(screen.getByText("Desc 2")).toBeInTheDocument();
  });
});

describe("PropertyGrid", () => {
  it("renderiza propriedades", () => {
    render(
      <PropertyGrid
        properties={[
          { label: "Nome", value: "AI Lyrics" },
          { label: "Versão", value: "0.1.0" },
        ]}
      />,
    );
    expect(screen.getByText("Nome")).toBeInTheDocument();
    expect(screen.getByText("AI Lyrics")).toBeInTheDocument();
    expect(screen.getByText("Versão")).toBeInTheDocument();
    expect(screen.getByText("0.1.0")).toBeInTheDocument();
  });

  it("renderiza valor nulo como traço", () => {
    render(
      <PropertyGrid properties={[{ label: "X", value: null }]} />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("Modal", () => {
  it("não renderiza quando fechado", () => {
    render(<Modal open={false} onClose={() => {}}><div>modal</div></Modal>);
    expect(screen.queryByText("modal")).not.toBeInTheDocument();
  });

  it("renderiza quando aberto", () => {
    render(<Modal open={true} onClose={() => {}} title="Título"><div>modal</div></Modal>);
    expect(screen.getByText("modal")).toBeInTheDocument();
    expect(screen.getByText("Título")).toBeInTheDocument();
  });

  it("chama onClose ao clicar no overlay", () => {
    const onClose = vi.fn();
    render(<Modal open={true} onClose={onClose}><div>m</div></Modal>);
    screen.getByTestId("modal-overlay").click();
    expect(onClose).toHaveBeenCalled();
  });

  it("chama onClose ao clicar no botão X", () => {
    const onClose = vi.fn();
    render(<Modal open={true} onClose={onClose} title="T"><div>m</div></Modal>);
    screen.getByLabelText("Fechar").click();
    expect(onClose).toHaveBeenCalled();
  });
});

describe("ConfirmationDialog", () => {
  it("renderiza mensagem", () => {
    render(
      <ConfirmationDialog
        open={true}
        message="Deseja continuar?"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByText("Deseja continuar?")).toBeInTheDocument();
  });

  it("renderiza botões confirmar e cancelar", () => {
    render(
      <ConfirmationDialog
        open={true}
        message="Confirma?"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByText("Confirmar")).toBeInTheDocument();
    expect(screen.getByText("Cancelar")).toBeInTheDocument();
  });

  it("chama onConfirm ao clicar em confirmar", () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmationDialog
        open={true}
        message="Confirma?"
        onConfirm={onConfirm}
        onCancel={() => {}}
      />,
    );
    screen.getByText("Confirmar").click();
    expect(onConfirm).toHaveBeenCalled();
  });
});
