UNIVERSITY CLASS PREPARATION — MOD INDEPENDENTE
================================================

Objetivo
--------
Adicionar a interação "Se Preparar para a Aula" às caixas de correio e
acioná-la automaticamente pelo aviso de uma hora antes da aula universitária.

Dependências
------------
- The Sims 4: Discover University.
- XML Injector v4.2 ou superior.
- Script Mods habilitados.

Arquivos gerados
----------------
- UniversityClassPreparation.ts4script
- UniversityClassPreparation.package

Instalação
----------
Coloque os dois arquivos na mesma pasta dentro de:
Documents\Electronic Arts\The Sims 4\Mods\UniversityClassPreparation\

Não remova nem substitua o AutoUniversityEnrollment. Este projeto é independente.

Comportamento pretendido
------------------------
Quando o jogo executar o aviso nativo de uma hora antes da aula, o mod tenta
enfileirar a interação na caixa de correio da residência carregada, com
prioridade alta. A interação deve encaminhar o Sim até a caixa de correio e
aguardar o início da próxima aula. Se o Sim não estiver na residência ou se
a interação não puder ser enfileirada, o comportamento nativo da EA é mantido.

Estado de validação
-------------------
O pacote de tuning é validado estruturalmente durante o build. A compilação
Python valida sintaxe, não APIs do jogo. A execução real, a rota até a caixa
de correio e a espera precisam ser testadas no The Sims 4 antes de considerar
o mod funcional.
