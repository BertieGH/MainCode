using Microsoft.EntityFrameworkCore.Storage;
using Survey.Core.Interfaces;
using Survey.Infrastructure.Data;

namespace Survey.Infrastructure.Repositories;

public class UnitOfWork : IUnitOfWork
{
    private readonly SurveyDbContext _context;
    private IDbContextTransaction? _transaction;

    public IQuestionBankRepository QuestionBankRepository { get; }
    public IQuestionCategoryRepository QuestionCategoryRepository { get; }
    public IUserRepository UserRepository { get; }

    public UnitOfWork(
        SurveyDbContext context,
        IQuestionBankRepository questionBankRepository,
        IQuestionCategoryRepository questionCategoryRepository,
        IUserRepository userRepository)
    {
        _context = context;
        QuestionBankRepository = questionBankRepository;
        QuestionCategoryRepository = questionCategoryRepository;
        UserRepository = userRepository;
    }

    public async Task<int> SaveChangesAsync()
    {
        return await _context.SaveChangesAsync();
    }

    public async Task BeginTransactionAsync()
    {
        _transaction = await _context.Database.BeginTransactionAsync();
    }

    public async Task CommitTransactionAsync()
    {
        if (_transaction != null)
        {
            await _transaction.CommitAsync();
            await _transaction.DisposeAsync();
            _transaction = null;
        }
    }

    public async Task RollbackTransactionAsync()
    {
        if (_transaction != null)
        {
            await _transaction.RollbackAsync();
            await _transaction.DisposeAsync();
            _transaction = null;
        }
    }

    public void Dispose()
    {
        _transaction?.Dispose();
        _context.Dispose();
    }
}
