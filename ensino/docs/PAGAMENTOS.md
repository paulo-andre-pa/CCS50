# Estudo: como receber pagamentos no Ensino Ekulihiso

O modelo é parecido com o do Superprof: o professor publica um anúncio com o seu **preço por hora**, o aluno **pede a reserva** de uma aula, o professor **aceita**, o aluno **paga à plataforma** e, depois da aula, a plataforma **transfere o valor ao professor** menos a comissão.

## 1. Opções de pagamento em Angola

| Opção | Como o aluno paga | Confirmação | Alcance | Integração |
|---|---|---|---|---|
| **Referência Multicaixa** (ProxyPay, AppyPay…) | Entidade + referência no ATM, na app Multicaixa Express ou no internet banking | Automática (webhook) | Muito alto: qualquer pessoa com conta bancária ou acesso a um ATM | Simples: API REST e webhook |
| **Multicaixa Express "push"** (EMIS GPO, através de um banco ou agregador) | Escreve o nº de telemóvel e aprova na app em ~90 segundos | Automática, imediata | Alto: a app Multicaixa Express é o canal com mais operações na rede | Média: contrato com banco, certificação técnica |
| **Carteiras móveis** (Unitel Money, Afrimoney) | Saldo da carteira, inclusive por USSD | Automática | Chega a quem não tem conta bancária | Através de um agregador (ex.: AppyPay) |
| **Transferência bancária / IBAN** | Transferência (também pela app Multicaixa Express) e envio do comprovativo | Manual, feita por um administrador | Alto | Nenhuma: basta uma conta bancária da empresa |
| **Cartões Visa/Mastercard** | Cartão internacional | Automática | Baixo para pagamentos internos | Gateway internacional; pouco útil no início |

## 2. Recomendação

**Fase 1 (lançamento, já implementada no código):**
1. **Referência Multicaixa através da ProxyPay** como método principal. Funciona para quase todos os alunos e encarregados, confirma automaticamente e não obriga a que o aluno tenha a app.
2. **Transferência bancária com comprovativo** como alternativa. Não precisa de contrato nenhum, por isso permite começar já, enquanto o contrato com a ProxyPay não estiver pronto.

**Fase 2:** acrescentar o **pagamento "push" Multicaixa Express** (via EMIS GPO, através do banco ou de um agregador como a ProxyPay ou a AppyPay). É o pagamento mais rápido no telemóvel.

**Fase 3:** **Unitel Money / Afrimoney** através de um agregador, para chegar a alunos sem conta bancária, sobretudo fora de Luanda.

**Porque a plataforma recebe e só depois paga ao professor:** protege o aluno (se a aula não acontecer, é reembolsado), protege o professor (só dá a aula depois de o pagamento estar confirmado) e garante a comissão. Os contactos só são revelados depois do pagamento, para que as aulas não sejam combinadas por fora.

## 3. Como funciona no site

```
Aluno pede reserva ──► Professor aceita ──► Aluno paga ──► Reserva confirmada ──► Aula dada ──► Repasse ao professor
   (pendente)            (aceite)        referência ou     (paga; contactos      (concluída)    (administrador marca
                                         transferência      visíveis)                            como pago)
```

- **Preço:** o total é preço/hora × nº de horas. Se o anúncio tiver "1ª aula grátis", a primeira hora da primeira reserva com esse professor é gratuita (e se o total for 0 a reserva fica confirmada logo que o professor aceita).
- **Comissão:** definida em `COMMISSION_PERCENT` (10% por omissão), descontada ao valor que o professor recebe. O aluno paga sempre o preço anunciado.
- **Referência:** válida 3 dias. A ProxyPay avisa o site em `POST /pagamentos/proxypay/webhook`. O site verifica a assinatura HMAC-SHA256 (`X-Signature`), regista cada notificação uma só vez e confirma a reserva se o montante estiver certo.
- **Transferência:** o aluno envia o comprovativo (PDF/imagem) e o administrador confirma em `/admin`.
- **Repasse:** em `/admin` aparece a lista de aulas concluídas, com o IBAN de cada professor. Depois de transferir, o administrador marca como pago.
- **Cancelamentos:** o aluno pode cancelar antes de pagar. Depois de pago, só o administrador cancela e faz o reembolso.

## 4. O que é preciso para activar os pagamentos reais

1. **Empresa registada** (NIF) e **conta bancária empresarial** num banco angolano.
2. **Contrato com a ProxyPay** (proxypay.co.ao) ou com outro agregador de referências. Recebe uma **chave da API** e uma **Entidade**. Peça e compare as tabelas de comissões por transacção antes de escolher.
3. Definir no servidor:
   ```
   PROXYPAY_API_KEY=...        # chave da API
   PROXYPAY_ENTITY=...         # a sua Entidade Multicaixa
   PROXYPAY_ENV=production     # ou sandbox para testes
   BANK_NAME=...  BANK_HOLDER=...  BANK_IBAN=AO06...
   COMMISSION_PERCENT=10
   ```
4. No painel da ProxyPay, configurar o webhook para `https://ensino.ekulihiso.com/pagamentos/proxypay/webhook`.
5. Testar primeiro em sandbox. A ProxyPay permite simular pagamentos, e o webhook deve confirmar a reserva sozinho.
6. Criar a conta de administrador: `flask --app app criar-admin email@dominio.ao`.

Sem `SECRET_KEY` definida (desenvolvimento), o site usa um **modo de testes**: gera referências fictícias e mostra um botão "Simular pagamento".

## 5. Questões legais e fiscais a confirmar

- **Receber dinheiro em nome de terceiros:** confirmar com um advogado ou o banco se receber os pagamentos e depois pagar aos professores exige alguma licença do BNA, ou se é preferível o modelo de comissão (a plataforma factura a comissão e o agregador divide o pagamento).
- **Facturação:** emitir facturas/recibos certificados (AGT) da comissão e, conforme o enquadramento, das aulas.
- **Professores:** como declaram os rendimentos (trabalhador independente).
- **Reembolsos e termos de uso:** publicar regras claras de cancelamento (por exemplo, reembolso total até 24 horas antes da aula).

## 6. Próximos passos técnicos

- Notificações por email/SMS (pedido de reserva, aceite, pagamento confirmado).
- Lembrete automático e expiração das reservas aceites e não pagas.
- Conclusão automática da aula alguns dias depois da data, se ninguém a contestar.
- Avaliações do professor depois da aula concluída.
- Pagamento "push" Multicaixa Express e carteiras móveis (fases 2 e 3).

## Fontes

- [Brochura do Banco BAI sobre a ProxyPay](https://www.bancobai.ao/media/1560/brochura-e_bai1.pdf)
- [Documentação Paybyrd: Multicaixa Express através da ProxyPay](https://docs.paybyrd.com/docs/multicaixa-express)
- [Access Bank: perguntas frequentes sobre o GPO da EMIS](https://angola.accessbankplc.com/access/media/documentos/Perguntas-Frequentes.pdf)
- [Expansão: Multicaixa Express já é o canal com mais operações na rede](https://www.expansao.co.ao/empresas/detalhe/multicaixa-express-ja-e-o-canal-com-mais-operacoes-na-rede-61836.html)
- [Ver Angola: limite diário de transferências no Multicaixa Express sobe para 500.000 Kz](https://www.verangola.net/va/pt/092025/BancaSeguros/46011/EMIS-aumenta-limite-diário-de-transferências-na-aplicação-Multicaixa-Express-para-500000-kwanzas.htm)
- [Entrevista ao The Business Year sobre a AppyPay (integração com Multicaixa Express, referências e Unitel Money)](https://dev.thebusinessyear.com/interview/daniel-cohen-angola-2025/)
- [Reclame Aqui: carregar o Unitel Money por referência](https://reclameaqui.ao/blog/carregar-unitel-money-multicaixa-express)
