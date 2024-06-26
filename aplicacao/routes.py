from flask import render_template, request, url_for, redirect, flash, session, abort
from aplicacao import app, database, bcrypt
from aplicacao.models import Servico, Funcionario, Barbearia, Agenda, Usuario
from datetime import datetime, timedelta
from aplicacao.forms import FormBuscarHorarios, FormConfirmarHorario, FormConfirmarAgendamento, FormCriarConta, FormLogin, FormPerfil
from flask_login import login_required, login_user, logout_user, current_user
from aplicacao.utils import sendgrid_mail, calcular_somas_por_mes, total_clientes_mes
from sqlalchemy import func, extract
import json

@app.errorhandler(403)
def access_denied(e):
    return redirect(url_for('home'))

@app.route('/')
def home():
    servicos = Servico.query.all()
    barbearia = Barbearia.query.first()
    nota = int(barbearia.nota)

    return render_template("home.html", servicos=servicos, barbearia=barbearia, nota=nota)

@app.route('/agendamento/<int:servico_id>', methods=['GET', 'POST'])
def agendamento(servico_id):

    if not current_user.is_authenticated:
        return redirect('/acessar')
    
    servico = Servico.query.filter_by(id=servico_id).first()

    form = FormBuscarHorarios()
    form_confirmar_horario = FormConfirmarHorario()

    lista_horarios = []

    horarios_validos = []
    
    if request.method == 'POST':
        if form.validate_on_submit():

            agenda = Agenda.query.filter_by(data=form.data.data, funcionario_id=int(form.funcionarios_disponiveis.data)).all()
            
            funcionario = Funcionario.query.filter_by(id=int(form.funcionarios_disponiveis.data)).first()

            session['funcionario'] = funcionario.nome
            session['servico'] = servico.id

            horario_atual = datetime.combine(form.data.data, funcionario.horario_inicio)
            horario_saida = datetime.combine(form.data.data, funcionario.horario_saida)
            almoco_saida = datetime.combine(form.data.data, funcionario.almoco_saida)
            almoco_entrada = datetime.combine(form.data.data, funcionario.almoco_inicio)

            total_minutos = servico.tempo.hour * 60 + servico.tempo.minute
            tempo_servico = timedelta(minutes=total_minutos)

            # Realize o loop enquanto o horário atual for menor que o horário de saída
            while ((horario_atual + tempo_servico) <= horario_saida):

                if ((horario_atual + tempo_servico) <= almoco_entrada):
                    lista_horarios.append(horario_atual)
                    horario_atual += tempo_servico
                elif (horario_atual >= almoco_saida):
                    lista_horarios.append(horario_atual)
                    horario_atual += tempo_servico
                else:
                    horario_atual = almoco_saida
                    lista_horarios.append(horario_atual)
                    horario_atual += tempo_servico

            for i in agenda:
                agenda_inicio = datetime.combine(i.data, i.hora_inicio)
                agenda_termino = datetime.combine(i.data, i.hora_termino)
                total_minutos = i.servico.tempo.hour * 60 + i.servico.tempo.minute
                tempo_servico = timedelta(minutes=total_minutos)

                for horario in lista_horarios:
                    if (agenda_inicio == horario):
                        continue
                    elif ((horario >= agenda_inicio) and (horario < agenda_termino)):
                        continue
                    else:
                        horarios_validos.append(horario)

                lista_horarios = horarios_validos

            horarios_validos = [horario for horario in lista_horarios if horario > datetime.now()]

            lista_horarios = [(item.strftime("%Y-%m-%d"), item.strftime("%H:%M:%S")) for item in horarios_validos]


            return render_template("agendamento.html", form=form, form_confirmar_horario=form_confirmar_horario, lista_horarios=lista_horarios, servico=servico)

        if form_confirmar_horario.validate_on_submit():

            if 'horario' in request.form:
                data_horario = datetime.strptime(request.form['horario'], "%Y-%m-%d %H:%M:%S")

                if data_horario > datetime.now():
                    session['data'] = data_horario.strftime("%d %B, %Y")
                    session['horario'] = data_horario.strftime("%H:%M:%S")

                    return redirect(url_for('finish'))
                else:
                    flash("Horário inválido!", "error")
                    return redirect(url_for('agendamento', servico_id=servico_id))
            else:
                return redirect(url_for('agendamento', servico_id=servico_id))

    return render_template("agendamento.html", form=form, servico=servico)

@app.route('/finish', methods=['GET', 'POST'])
@login_required
def finish():

    # session.pop('csrf_token', None)
    form = FormConfirmarAgendamento()

    usuario = Usuario.query.filter_by(id=session['usuario']).first()
    servico = Servico.query.filter_by(id=session['servico']).first()
    funcionario = Funcionario.query.filter_by(nome=session['funcionario']).first()

    session['email'] = usuario.email
    session['nome'] = usuario.nome
    session['telefone'] = usuario.telefone

    if form.validate_on_submit():

        horario_inicio = datetime.strptime(session['horario'],'%H:%M:%S')

        hora_termino = horario_inicio + timedelta(hours=servico.tempo.hour, minutes=servico.tempo.minute, seconds=servico.tempo.second)
        data = datetime.strptime(session['data'], '%d %B, %Y')


        novo_horario = Agenda(
                        servico_id=servico.id,
                        funcionario_id=funcionario.id,
                        usuario_id=current_user.id,
                        data=data,
                        hora_inicio=horario_inicio.time(),
                        hora_termino=hora_termino.time()
        )

        database.session.add(novo_horario)
        database.session.commit()

        titulo = f"Horário agendado: {session['horario']}!"
        mensagem = f"""
        <p>{current_user.nome}<p>
        <p>{servico.nome_servico}</p>
        <p>{session['horario']}</p>
        <p>{data}</p>
        <p>{funcionario.nome}</p><br>
        """

        sendgrid_mail("smaniottocaetano@gmail.com", titulo, mensagem)

        flash("Seu horário foi agendado com sucesso!", "success")
        return redirect("/")

    return render_template("finish.html", form=form, servico=servico)

@app.route('/acessar', methods=['GET', 'POST'])
def acessar():

    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == 'POST':

        if 'login' in request.form:
            return redirect('acessar/signin')
        elif 'register' in request.form:
            return redirect('acessar/signup')

    return render_template('sign.html')

@app.route('/acessar/signin', methods=['GET', 'POST'])
def signin():
    form = FormLogin()

    if form.validate_on_submit():
        usuario = Usuario.query.filter_by(email=form.email.data).first()
        if usuario and bcrypt.check_password_hash(usuario.senha, form.senha.data):
            login_user(usuario)
            flash("Logado com sucesso", "success")

            session['email'] = usuario.email
            session['nome'] = usuario.nome
            session['telefone'] = usuario.telefone
            session['usuario'] = usuario.id

            return redirect(url_for('home'))
        else:
            flash("Senha incorreta", "error")
            return redirect("/acessar/signin")
    
    return render_template('sign.html', form=form)

@app.route('/acessar/signup', methods=['GET', 'POST'])
def signup():
    form_criar_conta = FormCriarConta()

    if form_criar_conta.validate_on_submit():
        hash = bcrypt.generate_password_hash(form_criar_conta.senha.data).decode('utf-8')
        usuario = Usuario(
                    nome=form_criar_conta.nome.data,
                    email=form_criar_conta.email.data,
                    telefone=form_criar_conta.telefone.data,
                    senha=hash)
        
        database.session.add(usuario)
        database.session.commit()

        titulo = "Conta criada com sucesso!"
        mensagem = f"""
        <p>Olá {form_criar_conta.nome.data}, sua conta foi criada com sucesso!<p>
        <br> Caso não tenha sido você, entre em contato conosco respondendo a este email!
        """

        sendgrid_mail(form_criar_conta.email.data, titulo, mensagem)
        flash('Conta criada com sucesso!')
        login_user(usuario)

        session['usuario'] = usuario.id
        session['email'] = usuario.email
        session['nome'] = usuario.nome
        session['telefone'] = usuario.telefone

        return redirect('/')

    return render_template('sign.html', form_criar_conta=form_criar_conta)

@app.route("/logout")
@login_required
def logout():
    session.clear()
    logout_user()
    flash("Saiu com sucesso!", "success")
    return redirect(url_for('home'))


@app.route('/tasks')
@login_required
def tasks():

    if current_user.permissao != 1:
        return abort(403)

    hoje, proxima_semana = datas_da_semana()
    horarios_agendados = Agenda.query.filter(Agenda.data.between(hoje, proxima_semana)).order_by(Agenda.data).all()
    return render_template("tasks.html", horarios_agendados=horarios_agendados)

def datas_da_semana():
    hoje = datetime.today().date()
    proxima_semana = hoje + timedelta(days=7)
    return hoje, proxima_semana

@app.route('/dashboard')
@login_required
def dashboard():

    if current_user.permissao != 1:
        return abort(403)
    
    ano_atual = datetime.now().year
    mes_atual = datetime.now().month
    
    # cards
    result = database.session.query(Agenda.status, func.count(Agenda.id)).group_by(Agenda.status).all()
    cartoes = {'Pendente': 0, 'Concluído': 0, 'Cancelado': 0}

    for status, count in result:
        cartoes[status] = count

    # grafico de pizza
    total_por_funcionario = database.session.query(Funcionario.nome, func.count(Agenda.id)).\
    join(Agenda).\
    filter(Agenda.status == 'Concluído').\
    filter(func.extract('year', Agenda.data) == ano_atual).\
    filter(func.extract('month', Agenda.data) == mes_atual).\
    group_by(Funcionario.nome).all()

    funcionarios = {}
    for nome, total in total_por_funcionario:
        funcionarios[nome] = total

    # grafico de barra - renda mensal
    ano_atual = datetime.now().year
    somas_por_mes = calcular_somas_por_mes(ano_atual)

    total_anual = sum(somas_por_mes.values())
    somas_por_mes['Média'] = total_anual / 12
    somas_por_mes['Total'] = total_anual
    
    # grafico de pontos
    total_clientes = total_clientes_mes(ano_atual)

    return render_template('dashboard.html', cartoes=cartoes, meses=list(somas_por_mes.keys()), somas=list(somas_por_mes.values()), total_por_funcionarios=list(funcionarios.values()), nomes_funcionarios=list(funcionarios.keys()),
                           meses_clientes=list(total_clientes.keys()), total_clientes=list(total_clientes.values()))

@app.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    form = FormPerfil()

    if request.method == 'POST' and form.validate_on_submit():
        current_user.nome = form.nome.data
        current_user.telefone = form.telefone.data
        database.session.commit()

        flash("Dados alterados com sucesso!", "success")
        return redirect(url_for('home'))
    else:
        form.nome.data = current_user.nome
        form.telefone.data = current_user.telefone
        form.email.data = current_user.email
        return render_template('perfil.html', form=form)
    
@app.route('/agenda', methods=['GET', 'POST'])
@login_required
def agenda():
    horarios_anteriores = []
    horarios_ativos = []

    historico = Agenda.query.filter_by(usuario_id=current_user.id).all()

    for agendamento in historico:
        if agendamento.status in ['Cancelado', 'Concluído']:
            horarios_anteriores.append(agendamento)
        elif agendamento.status == 'Pendente':
            horarios_ativos.append(agendamento)

    return render_template('agenda.html', horarios_anteriores=horarios_anteriores, horarios_ativos=horarios_ativos)

@app.route('/agenda/<int:horario_id>', methods=['GET', 'POST'])
@login_required
def excluir_horario(horario_id):

    historico = Agenda.query.filter_by(usuario_id=current_user.id).all()

    for agendamento in historico:
        if agendamento.id == int(horario_id):
            database.session.delete(agendamento)
            database.session.commit()
            flash("Horário cancelado!", "success")

    return redirect('/agenda')