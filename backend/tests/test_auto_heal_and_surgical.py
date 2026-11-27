from app.agent.htmlkit import auto_heal_interactivity_and_assets
from app.agent.graph import locate_surgical_target


def test_auto_heal_orphaned_anchor_and_empty_links():
    raw = """
    <header data-mb-id="hdr">
        <a href="#especificacoes" data-mb-id="link-specs">Ver Especificações</a>
        <a href="#" data-mb-id="link-empty">Saiba mais</a>
    </header>
    <section data-mb-id="section-especificacoes" class="p-8">
        <h2>Especificações Técnicas</h2>
    </section>
    """
    healed, warnings = auto_heal_interactivity_and_assets(raw)
    assert 'id="especificacoes"' in healed
    assert 'data-toast="Ação em demonstração"' in healed


def test_auto_heal_dead_buttons():
    raw = """
    <div data-mb-id="card">
        <button data-mb-id="btn-test">Agende um test drive</button>
        <button data-mb-id="btn-active" data-go="Agendamento">Ir para Agendamento</button>
    </div>
    """
    healed, warnings = auto_heal_interactivity_and_assets(raw)
    assert 'data-toast="Agende um test drive confirmado!"' in healed
    # Botão com data-go não deve ser alterado
    assert 'data-go="Agendamento"' in healed


def test_auto_heal_images_fallback():
    raw = """
    <img src="https://images.unsplash.com/photo-1" data-mb-id="car-img" alt="Carro">
    """
    healed, warnings = auto_heal_interactivity_and_assets(raw)
    assert 'onerror=' in healed
    assert 'loading="lazy"' in healed


def test_locate_surgical_target_button():
    html = """
    <div data-mb-id="hero" class="p-8">
        <h1 data-mb-id="hero-title">Honda Civic Type R</h1>
        <button data-mb-id="btn-cta" class="bg-red-600 text-white">Quero conhecer</button>
    </div>
    """
    target = locate_surgical_target(html, "Mude a cor do botão para verde escuro")
    assert target is not None
    assert target.mbId == "btn-cta"
    assert target.tag == "button"


def test_locate_surgical_target_heading():
    html = """
    <div data-mb-id="hero" class="p-8">
        <h1 data-mb-id="main-title">Nascido para a pista</h1>
        <p data-mb-id="desc">Descrição do carro esportivo.</p>
    </div>
    """
    target = locate_surgical_target(html, "Mude o título principal para Domine o asfalto")
    assert target is not None
    assert target.mbId == "main-title"
    assert target.tag == "h1"
