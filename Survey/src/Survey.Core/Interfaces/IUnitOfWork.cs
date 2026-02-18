namespace Survey.Core.Interfaces;

public interface IUnitOfWork : IDisposable
{
    IQuestionBankRepository QuestionBankRepository { get; }
    IQuestionCategoryRepository QuestionCategoryRepository { get; }
    IUserRepository UserRepository { get; }
    Task<int> SaveChangesAsync();
    Task BeginTransactionAsync();
    Task CommitTransactionAsync();
    Task RollbackTransactionAsync();
}
