using Survey.Core.Entities;

namespace Survey.Core.Interfaces;

public interface IFieldMappingRepository : IRepository<FieldMapping>
{
    Task<IEnumerable<FieldMapping>> GetAllMappingsAsync();
    Task<FieldMapping?> GetMappingByIdAsync(int id);
}
